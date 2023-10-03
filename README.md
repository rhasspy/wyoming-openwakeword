# Wyoming openWakeWord

[Wyoming protocol](https://github.com/rhasspy/wyoming) server for the [openWakeWord](https://github.com/dscripka/openWakeWord) wake word detection system.


## Home Assistant Add-on

[![Show add-on](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=core_openwakeword)

[Source](https://github.com/home-assistant/addons/tree/master/openwakeword)

## Docker Image

``` sh
docker run -it -p 10400:10400 rhasspy/wyoming-openwakeword \
    --model 'ok_nabu' \
    --model 'hey_jarvis' \
    --model 'hey_rhasspy' \
    --model 'hey_mycroft' \
    --model 'alexa' \
    --preload-model 'ok_nabu'
```

[Source](https://github.com/rhasspy/wyoming-addons/tree/master/openwakeword)
