# Third-Party Licenses

Shadow-clerk depends on the following open-source packages. Each package is subject to its own license terms.

| Package | License | URL |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT | https://github.com/spatialaudio/python-sounddevice/blob/master/LICENSE |
| [webrtcvad-wheels](https://github.com/nickcosmo/webrtcvad-wheels) | MIT | https://github.com/wiseman/py-webrtcvad/blob/master/LICENSE |
| [numpy](https://numpy.org/) | BSD-3-Clause | https://github.com/numpy/numpy/blob/main/LICENSE.txt |
| [PyYAML](https://pyyaml.org/) | MIT | https://github.com/yaml/pyyaml/blob/main/LICENSE |
| [openai](https://github.com/openai/openai-python) | Apache-2.0 | https://github.com/openai/openai-python/blob/main/LICENSE |
| [pynput](https://github.com/moses-palmer/pynput) | LGPL-3.0 | https://github.com/moses-palmer/pynput/blob/master/COPYING.LGPL |
| [evdev](https://github.com/gvalkov/python-evdev) | BSD-3-Clause | https://github.com/gvalkov/python-evdev/blob/main/LICENSE |

## Notes

- **pynput** is licensed under LGPL-3.0. Shadow-clerk uses pynput as a dynamically-linked library (imported via pip) without modification. This is compatible with shadow-clerk's MIT license. If you modify pynput's source code and distribute it, those modifications must be released under LGPL-3.0.
- **faster-whisper** depends on [CTranslate2](https://github.com/OpenNMT/CTranslate2) (MIT license). Whisper models may have separate license terms depending on the model used.
