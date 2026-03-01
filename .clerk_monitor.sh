#!/bin/bash
# Voice command monitor for shadow-clerk
UTIL=~/.claude/skills/shadow-clerk/clerk-util

echo "Voice command monitor started. Waiting for commands..."

while true; do
    CMD=$($UTIL poll-command 5 2>/dev/null)

    if [ "$CMD" = "stopped" ]; then
        echo "Recorder stopped. Exiting monitor."
        exit 0

    elif [ "$CMD" = "translate_start" ]; then
        $UTIL write .clerk_command "" 2>/dev/null
        CONFIG=$($UTIL read-config 2>/dev/null)
        LANG=$(echo "$CONFIG" | grep "^translate_language:" | awk '{print $2}')
        PROVIDER=$(echo "$CONFIG" | grep "^llm_provider:" | awk '{print $2}')
        echo "翻訳開始: language=$LANG, provider=$PROVIDER"

        # Translation loop
        while true; do
            SESSION=$($UTIL read .clerk_session 2>/dev/null)
            if [ -z "$SESSION" ] || echo "$SESSION" | grep -q "^no"; then
                TRANSCRIPT="transcript-20260228.txt"
            else
                TRANSCRIPT=$(echo "$SESSION" | tr -d '[:space:]')
            fi

            OFFSET=$($UTIL read .translate_offset 2>/dev/null)
            if [ -z "$OFFSET" ] || echo "$OFFSET" | grep -q "^no"; then
                OFFSET=0
            fi
            OFFSET=$(echo "$OFFSET" | tr -d '[:space:]')

            NEWTEXT=$($UTIL read-from "$TRANSCRIPT" "$OFFSET" 2>/dev/null)

            if [ -n "$NEWTEXT" ]; then
                BASENAME=$(echo "$TRANSCRIPT" | sed 's/\.txt$//')
                OUTFILE="${BASENAME}-${LANG}.txt"

                if [ "$PROVIDER" = "api" ]; then
                    echo "Running LLM translate via API..."
                    RESULT=$($UTIL run-llm translate "$LANG" --file "$TRANSCRIPT" --offset "$OFFSET" --verbose 2>&1)
                    echo "$RESULT"
                    # Extract translated content (non-comment, non-empty lines)
                    TRANSLATED=$(echo "$RESULT" | grep -v "^#" | grep -v "^DEBUG" | grep -v "^---" || true)
                    if [ -n "$TRANSLATED" ]; then
                        while IFS= read -r tline; do
                            if [ -n "$tline" ]; then
                                $UTIL append "$OUTFILE" "$tline"
                            fi
                        done <<< "$TRANSLATED"
                    fi
                else
                    echo "Claude translation mode - lines:"
                    echo "$NEWTEXT"
                fi

                NEWSIZE=$($UTIL size "$TRANSCRIPT" 2>/dev/null)
                $UTIL write .translate_offset "$NEWSIZE"
                echo "Offset updated to $NEWSIZE"
            else
                # No new lines, poll for commands
                PCMD=$($UTIL poll-command 5 2>/dev/null)
                if [ "$PCMD" = "translate_stop" ]; then
                    $UTIL write .clerk_command "" 2>/dev/null
                    echo "翻訳を停止しました"
                    break
                elif [ "$PCMD" = "stopped" ]; then
                    echo "Recorder stopped. Exiting monitor."
                    exit 0
                fi
                # Otherwise continue translation loop
            fi
        done

    elif [ "$CMD" = "translate_stop" ]; then
        $UTIL write .clerk_command "" 2>/dev/null
        echo "translate_stop received (not in translation). Continuing..."
    fi
    # For any other/empty command, continue the main loop
done
