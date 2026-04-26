# Architecture Validation Rules

Twelve rules that MUST hold true for the OT Range network to correctly
implement the IEC 62443 Purdue Reference Model.

## Network Isolation

1. **Corporate zone cannot reach process zone.**
   `ip netns exec svc-corp-web ping -c1 -W2 10.0.4.101` MUST fail.

2. **Corporate zone cannot reach safety zone.**
   `ip netns exec svc-corp-web ping -c1 -W2 10.0.5.201` MUST fail.

3. **DMZ cannot reach process zone directly.**
   `ip netns exec svc-historian ping -c1 -W2 10.0.4.101` MUST fail.

4. **No ACCEPT firewall rules target the safety zone.**
   `iptables -L OT-RANGE-FORWARD -n | grep -c "10.0.5"` MUST return 0.

## Dual/Triple Homing

5. **SCADA HMI is dual-homed** on br-scada (10.0.3.10) and br-process (10.0.4.10).

6. **Engineering WS is triple-homed** on br-scada (10.0.3.20), br-process (10.0.4.20), and br-safety (10.0.5.20).

7. **EWS can reach process zone** via its dual-homed interface.
   `ip netns exec svc-eng-ws ping -c1 -W2 10.0.4.101` MUST succeed.

8. **EWS can reach safety zone** via its triple-homed interface.
   `ip netns exec svc-eng-ws ping -c1 -W2 10.0.5.201` MUST succeed.

## Safety Bridge

9. **Safety bridge listens on EWS localhost:10102.**
   `ip netns exec svc-eng-ws ss -tlnp | grep 10102` MUST show LISTEN.

10. **Safety bridge proxies to 10.0.5.201:102** (S7comm on safety PLC).

## BMS Placement

11. **BACnet BMS is on corporate network** at 10.0.1.20, NOT on process network.

## Idempotency

12. **Setup script is idempotent.** Running teardown then setup twice in succession produces no errors and the same state.
