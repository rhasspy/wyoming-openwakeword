# Changelog

## 1.10.1

- Handle auto-filled audio

## 1.10.0

- Upgrade to wyoming 1.5.3
- Add wake word phrase

## 1.9.0

- Add tests and Github actions
- Handle wake word aliases correctly
- Autofill silence when client connects
- Wait for processing to finish on audio-stop before sending not-detected
- Add --log-format argument
- Add --version argument

## 1.8.1

- Remove batching from wake word processing since not all models support it

## 1.8.0

- Include fix for potential deadlock
- Only process wake words that a client requests

## 1.7.1

- Always use wake word file name as key

## 1.7.0

- Make wake word loading completely dynamic (new models are automatically discovered)
- Rebuild Wyoming info message on each request
- Deprecate --model

## 1.5.1

- Include language in wake word descriptions

## 1.5.0

- Remove webrtc
- Remove audio options related to webrtc
- Remove wake word option (dynamic loading)
- Dynamically load wake word models

## 1.4.0

- Add noise suppression/auto gain with webrtc

## 1.1.0

- Initial release

