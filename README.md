### HomeAssistant-KKRP01AClimate
Custom component for KKRP01A Daikin controller

![Image of Preview1](https://github.com/mobicek/HomeAssistant-KKRP01AClimate/blob/main/images/preview1.png)
![Image of Preview2](https://github.com/mobicek/HomeAssistant-KKRP01AClimate/blob/main/images/preview2.png)

Installation:

1. In your **configuration.yaml** add the following:

```
climate:
  - platform: kkrp01a
    name: Daikin
    host: <host_ip>
```    

2. Copy kkrp01a component to **config_dir/custom_components**   

3. Restart your Home Assistant server
