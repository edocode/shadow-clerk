YEAR := $(shell date +%Y)
AUTHOR := Atsushi Kato

.PHONY: license dupcheck mypy test help slides slides-pdf build clean-dist publish publish-test extension-zip

# tests/ は pytest 形式と、自前の check() で数えるスクリプト形式が混在する。
# スクリプト形式は「__main__ ガードを持つ」か「行頭の sys.exit / raise SystemExit で
# import 時に自走する」もの。後者を取りこぼすと pytest の収集が SystemExit で落ちる。
# (grep のパターンに括弧を入れると make が $(shell ...) の終端を見失う)
# それ以外は pytest に渡す。`import pytest` の有無で分けると、pytest 形式でも
# pytest を import しないファイルが python 実行に回り、何も実行しないまま PASS になる。
# watchdog は実デバイスを開くので除く (CLAUDE.md 参照)
ALL_TESTS := $(filter-out tests/test_audio_capture_watchdog.py,$(wildcard tests/test_*.py))
SCRIPT_FILES := $(filter $(shell grep -l '__main__\|^sys\.exit\|^raise SystemExit' tests/test_*.py),$(ALL_TESTS))
PYTEST_FILES := $(filter-out $(SCRIPT_FILES),$(ALL_TESTS))

license: ## Generate LICENSE file
	@sed 's/Copyright (c) [0-9]*/Copyright (c) $(YEAR)/' LICENSE > LICENSE.tmp && mv LICENSE.tmp LICENSE
	@echo "LICENSE updated (year: $(YEAR))"

dupcheck: ## Check duplicate code (pylint R0801)
	uv run pylint --disable=all --enable=R0801 src/shadow_clerk/

mypy: ## Type check with mypy
	uv run mypy src/shadow_clerk/

# スクリプト形式は conftest.py を通らないので、本物のデータフォルダを書かないよう一時フォルダを渡す
test: ## Run every test (pytest files + script-style files; ~3 min, console PTY tests are slow)
	uv run pytest -q $(PYTEST_FILES)
	@fail=0; export SHADOW_CLERK_DATA_DIR=$$(mktemp -d -t shadow-clerk-test-XXXXXX); for f in $(SCRIPT_FILES); do \
	  if uv run python $$f >/dev/null 2>&1; then echo "PASS $$f"; else echo "FAIL $$f"; fail=1; fi; \
	done; exit $$fail

slides: ## Build HTML slides from docs/slides.md (renders Mermaid via mmdc)
	npx -y -p @mermaid-js/mermaid-cli mmdc -p docs/.puppeteer-config.json -i docs/slides.md -o docs/slides.rendered.md
	npx -y @marp-team/marp-cli docs/slides.rendered.md -o docs/slides.html --allow-local-files
	@echo "→ docs/slides.html"

slides-pdf: ## Build PDF slides from docs/slides.md (renders Mermaid via mmdc)
	npx -y -p @mermaid-js/mermaid-cli mmdc -p docs/.puppeteer-config.json -i docs/slides.md -o docs/slides.rendered.md
	npx -y @marp-team/marp-cli docs/slides.rendered.md --pdf -o docs/slides.pdf --allow-local-files
	@echo "→ docs/slides.pdf"

# Chrome ウェブストアに上げる zip。ストアは manifest の key を受け付けないので外す（ストア版の ID はストアが付ける）。
# 文書（README・ストア掲載文・プライバシーポリシー）は拡張の動作に要らないので入れない
EXT_VERSION = $(shell uv run python -c "import json;print(json.load(open('extension/manifest.json'))['version'])")
extension-zip: ## Build the Chrome Web Store upload zip into dist/
	rm -rf dist/extension && mkdir -p dist/extension
	cp -R extension/. dist/extension/
	rm -rf dist/extension/README.md dist/extension/store
	uv run python -c "import json;p='dist/extension/manifest.json';m=json.load(open(p));m.pop('key');json.dump(m,open(p,'w'),ensure_ascii=False,indent=2)"
	rm -f dist/shadow-clerk-extension-$(EXT_VERSION).zip
	cd dist/extension && zip -qr ../shadow-clerk-extension-$(EXT_VERSION).zip .
	@echo "dist/shadow-clerk-extension-$(EXT_VERSION).zip"

clean-dist: ## Remove dist/ build artifacts
	rm -rf dist/

build: clean-dist ## Build sdist + wheel into dist/
	uv build
	uv run --with twine twine check dist/*

publish-test: build ## Upload to TestPyPI (requires [testpypi] in ~/.pypirc)
	uv run --with twine twine upload --repository testpypi dist/*

publish: build ## Upload to PyPI (requires [pypi] in ~/.pypirc)
	uv run --with twine twine upload dist/*

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'
