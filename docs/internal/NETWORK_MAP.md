# Network Map

```
                          +------------------+
  [ATTACKER LAPTOP] ----->|  CORP  10.0.1/24 |
                          |  .1   gateway    |
                          |  .10  corp-web   |
                          +--------+---------+
                                   |
                          +--------v---------+
                          |   DMZ  10.0.2/24 |
                          |  .1   gateway    |
                          |  .10  historian  |
                          |  .30  opcua-gw   |
                          +--------+---------+
                                   |
                          +--------v---------+
                          |  SCADA 10.0.3/24 |
                          |  .1   gateway    |
                          |  .10  scada-hmi  |
                          |  .20  eng-ws     |
                          |  .30  ids-monitor|
                          +--------+---------+
                                   |
                          +--------v---------+
                          | PROCESS 10.0.4/24|
                          |  .1   gateway    |
                          |  .101 plc-intake |
                          |  .102 plc-chem   |
                          |  .103 plc-filter |
                          |  .104 plc-distrib|
                          +--------+---------+
                                   |
                          +--------v---------+
                          | SAFETY 10.0.5/24 |
                          |  .1   gateway    |
                          |  .201 safety-sis |
                          +------------------+
```

Traffic between zones is mediated by iptables rules - see
`config/network/firewall-rules.sh`.
