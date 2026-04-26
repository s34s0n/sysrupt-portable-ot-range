/* SCADA HMI Dashboard - Fetch polling (works through SSH tunnels) */
(function() {
    var ch8Shown = false;
    var ch9Shown = false;
    var ch10Shown = false;

    function updateDashboard(d) {
        // Tank level
        var level = d.tank_level || 72;
        var tankEl = document.getElementById('tank-water');
        if (tankEl) {
            var maxH = 68;
            var h = (level / 100) * maxH;
            tankEl.setAttribute('height', h.toFixed(1));
            tankEl.setAttribute('y', (148 - h).toFixed(1));
        }
        setText('tank-val', level.toFixed(1) + '%');

        // Pumps
        var p1 = d.pump1_running !== false;
        var p2 = d.pump2_running === true;
        setIndicator('pump1', p1);
        setText('pump1-status', p1 ? 'RUN' : 'STOP');
        setClass('pump1-status', p1 ? 'status-on' : 'status-off');
        setIndicator('pump2', p2);
        setText('pump2-status', p2 ? 'RUN' : 'STOP');
        setClass('pump2-status', p2 ? 'status-on' : 'status-off');

        // Chemical dosing
        var cl = d.chlorine_ppm || 2.5;
        var clEl = document.getElementById('cl-val');
        setText('cl-val', cl.toFixed(2) + ' ppm');
        if (clEl) {
            if (cl > 6.0) clEl.setAttribute('class', 'svg-value val-danger');
            else if (cl > 4.0) clEl.setAttribute('class', 'svg-value val-warn');
            else clEl.setAttribute('class', 'svg-value val-normal');
        }

        setText('ph-val', (d.ph || 7.2).toFixed(2));
        setText('temp-val', (d.temperature || 18.5).toFixed(1) + ' \u00B0C');
        setText('pid-val', (d.pid_mode || 'auto').toUpperCase());
        setText('sp-val', (d.pid_setpoint || 2.5).toFixed(2) + ' ppm');
        setText('flow-val', (d.flow_rate || 850).toFixed(0) + ' GPM');

        // Filter beds
        var fdp = d.filter_dp || [8.2, 7.5, 9.1, 6.8];
        setText('f1-val', fdp[0].toFixed(1) + ' psi');
        setText('f2-val', fdp[1].toFixed(1) + ' psi');
        setText('f3-val', fdp[2].toFixed(1) + ' psi');
        setText('f4-val', fdp[3].toFixed(1) + ' psi');

        // Distribution
        var dp = d.dist_pressure || d.distribution_pressure || 62;
        var dpEl = document.getElementById('dist-val');
        setText('dist-val', dp.toFixed(1) + ' psi');
        if (dpEl) {
            if (dp > 80) dpEl.setAttribute('class', 'svg-value val-danger');
            else if (dp > 64) dpEl.setAttribute('class', 'svg-value val-warn');
            else dpEl.setAttribute('class', 'svg-value val-normal');
        }
        setText('dist-flow', (d.flow_rate || 850).toFixed(0) + ' GPM');

        // Power
        var pw = d.power_status || 'normal';
        setText('power-val', pw.toUpperCase());
        setFill('power-ind', pw === 'normal' ? '#00cc66' : '#ff4444');

        // SIS
        var sis = d.sis_status || 'armed';
        setText('sis-val', sis.toUpperCase());
        if (sis === 'tripped') {
            setFill('sis-ind', '#ff4444');
            document.getElementById('sis-overlay').style.display = 'flex';
        } else if (sis === 'maintenance') {
            setFill('sis-ind', '#ffaa00');
            setText('sis-val', 'BYPASSED');
            document.getElementById('sis-overlay').style.display = 'none';
        } else {
            setFill('sis-ind', '#00cc66');
            document.getElementById('sis-overlay').style.display = 'none';
        }

        // Mode and alarm
        setText('mode-text', (d.pid_mode || 'auto').toUpperCase() === 'AUTO' ? 'AUTOMATIC' : 'MANUAL');
        var alarmActive = d.alarm_active === true;
        var alarmInhibit = d.alarm_inhibit === true;
        var alarmEl = document.getElementById('alarm-text');
        var alarmCard = document.getElementById('alarm-card');
        if (alarmActive && !alarmInhibit) {
            setText('alarm-text', 'ACTIVE');
            if(alarmEl) alarmEl.className = 'val-danger';
            if(alarmCard) {
                alarmCard.style.display = 'block';
                document.getElementById('alarm-msg').textContent = 'High chlorine level: ' + cl.toFixed(2) + ' ppm';
            }
        } else {
            setText('alarm-text', 'NONE');
            if(alarmEl) alarmEl.className = 'val-ok';
            if(alarmCard) alarmCard.style.display = 'none';
        }

        setText('update-time', d.timestamp || new Date().toISOString());

        // CH-08 flag (inside SVG)
        if (d.flag_ch8 && !ch8Shown) {
            ch8Shown = true;
            var fb = document.getElementById('flag-box');
            var ft = document.getElementById('flag-title');
            var fm = document.getElementById('flag-msg');
            if (fb) fb.style.display = 'block';
            if (ft) { ft.style.display = 'block'; ft.textContent = 'CHALLENGE 8 COMPLETE!'; }
            if (fm) { fm.style.display = 'block'; fm.textContent = d.flag_ch8; }
        }

        // CH-09 flag (reuse same box, update text)
        if (d.flag_ch9 && !ch9Shown) {
            ch9Shown = true;
            var fb = document.getElementById('flag-box');
            var ft = document.getElementById('flag-title');
            var fm = document.getElementById('flag-msg');
            if (fb) fb.style.display = 'block';
            if (ft) { ft.style.display = 'block'; ft.textContent = 'CHALLENGE 9 COMPLETE!'; }
            if (fm) { fm.style.display = 'block'; fm.textContent = d.flag_ch9; }
        }

        // CH-10 VICTORY - full compromise with dramatic overlay
        if (d.flag_ch10 && !ch10Shown) {
            ch10Shown = true;
            // Show flag in SVG
            var fb = document.getElementById('flag-box');
            var ft = document.getElementById('flag-title');
            var fm = document.getElementById('flag-msg');
            if (fb) { fb.style.display = 'block'; fb.setAttribute('stroke', '#ff0000'); fb.setAttribute('fill', '#1a0000'); }
            if (ft) { ft.style.display = 'block'; ft.textContent = 'PLANT COMPROMISED!'; ft.style.fill = '#ff0000'; }
            if (fm) { fm.style.display = 'block'; fm.textContent = d.flag_ch10; fm.style.fill = '#ff4444'; }
            // Show victory overlay
            var vo = document.getElementById('victory-overlay');
            var vf = document.getElementById('victory-flag-text');
            if (vo) vo.style.display = 'block';
            if (vf) vf.textContent = d.flag_ch10;
        }
    }

    function poll() {
        fetch('/api/status')
            .then(function(r) { return r.json(); })
            .then(function(d) { updateDashboard(d); })
            .catch(function() {});
    }

    setInterval(poll, 1000);
    poll();

    function setText(id, val) {
        var el = document.getElementById(id);
        if (el) el.textContent = val;
    }
    function setFill(id, color) {
        var el = document.getElementById(id);
        if (el) el.setAttribute('fill', color);
    }
    function setClass(id, cls) {
        var el = document.getElementById(id);
        if (el) el.setAttribute('class', 'svg-status ' + cls);
    }
    function setIndicator(id, on) {
        var el = document.getElementById(id);
        if (el) el.setAttribute('stroke', on ? '#00cc66' : '#666');
    }
})();
