# Wyoming openWakeWord

[Wyoming protocol](https://github.com/rhasspy/wyoming) server for the [openWakeWord](https://github.com/dscripka/openWakeWord) wake word detection system.


## Home Assistant Add-on

[![Show add-on](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=core_openwakeword)

[Source](https://github.com/home-assistant/addons/tree/master/openwakeword)


## Local Install

Clone the repository and set up Python virtual environment:

``` sh
git clone https://github.com/rhasspy/wyoming-openwakeword.git
cd wyoming-openwakeword
script/setup
```

Run a server that anyone can connect to:

``` sh
script/run --uri 'tcp://0.0.0.0:10400'
```

See `script/run --help` for more options, including:

* `--custom-model-dir <DIR>` - look for custom wake word models in `<DIR>`
* `--debug` - print lots of information to console


## Docker Image

``` sh
docker run -it -p 10400:10400 rhasspy/wyoming-openwakeword \
    --preload-model 'ok_nabu'
```

### Custom Models

```sh
docker run -it -p 10400:10400 -v /path/to/custom/models:/custom rhasspy/wyoming-openwakeword \
    --preload-model 'ok_nabu' \
    --custom-model-dir /custom
```

### Docker Compose
```
services:
  wyoming-openwakeword:
    image: rhasspy/wyoming-openwakeword
    container_name: wyoming-openwakeword
    command:
      - --preload-model
      - 'ok_nabu' # Change this to a supported wake word. Supported wake words include ok_nabu, hey_jarvis, alexa, hey_mycroft and hey_rhasspy.
      # Uncomment the below lines to use a custom wake word. You can find custom wake words at https://github.com/fwartner/home-assistant-wakewords-collection.
      # - --custom-model-dir
      # - /custom/en/wake_word
    # volumes:
      # - /path/to/wake/words:/custom:ro
    ports:
      - 10400:10400
    restart: always

```

[Source](https://github.com/rhasspy/wyoming-addons/tree/master/openwakeword)
