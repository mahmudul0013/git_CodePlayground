//http://127.0.0.1:5500/index.html#
// --- GLOBAL VARIABLES ---
let timerInterval;
let levelInterval;
let startTime;
let elapsedSeconds = 0;
let tankLevelPercent = 0;
let machineState = 'STOP'; // START, STOP, HOLD
let valveOpening = 50;
let alarmTriggered = false;

const possibleFaults = [
    { severity: 'CRITICAL', msg: 'Motor Overheating - Temp > 95C' },
    { severity: 'WARNING', msg: 'VFD Communication Timeout' },
    { severity: 'CRITICAL', msg: 'Vibration Sensor High Threshold' },
    { severity: 'WARNING', msg: 'Low Lubricant Pressure' }
];

// --- NAVIGATION ---
function showPage(pageId) {
    document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
    document.getElementById(pageId).classList.add('active');
}

// --- MAIN CONTROL LOGIC ---
function controlMachine(command) {
    machineState = command;
    const statusEl = document.getElementById('machineStatus');
    const fluid = document.getElementById('fluidFlow');
    const alarmAlert = document.getElementById('alarmAlert');
    const animContainer = document.getElementById('animationContainer');

    // Reset intervals and UI states
    clearInterval(timerInterval);
    clearInterval(levelInterval);
    alarmAlert.style.display = 'none';
    alarmTriggered = false;
    animContainer.innerHTML = '';
    
    if (command === 'START') {
        statusEl.innerText = 'RUNNING';
        statusEl.className = 'status-running';
        
        // Fluid Animation
        fluid.classList.remove('flow-off');
        fluid.classList.add('flow-running');
        updateFlowSpeed(); 
        
        // Button Animation
        animContainer.innerHTML = '<div class="spinner"></div>';
        
        startTimer();
        startTankFilling();
    } 
    else if (command === 'HOLD') {
        statusEl.innerText = 'ON HOLD';
        statusEl.className = 'status-held';
        
        // Pause Flow
        fluid.style.animationPlayState = 'paused';
        
        // Button Animation
        animContainer.innerHTML = '<div class="pulse-circle"></div>';
        
        startTimer();
    } 
    else if (command === 'STOP') {
        statusEl.innerText = 'STOPPED';
        statusEl.className = 'status-stopped';
        
        // Reset Process
        fluid.classList.add('flow-off');
        fluid.classList.remove('flow-running');
        tankLevelPercent = 0; 
        updateTankUI();
        
        elapsedSeconds = 0;
        updateTimerDisplay();
    }
    logEvent(`Machine command sent: ${command}`);
}

// --- VALVE & PROCESS LOGIC ---
function updateValve(val) {
    valveOpening = val;
    document.getElementById('valveValue').innerText = val;
    if (machineState === 'START') {
        updateFlowSpeed();
    }
}

function updateFlowSpeed() {
    const fluid = document.getElementById('fluidFlow');
    // Speed calculation: Higher valve % makes the animation duration shorter (faster)
    const speed = 2.5 - (valveOpening / 100 * 2.3); 
    fluid.style.animationDuration = `${speed}s`;
    fluid.style.animationPlayState = 'running';
}

function startTankFilling() {
    levelInterval = setInterval(() => {
        if (machineState === 'START' && tankLevelPercent < 100) {
            // Fill rate is determined by valve opening percentage
            tankLevelPercent += (valveOpening / 100) * 0.4; 
            if (tankLevelPercent > 100) tankLevelPercent = 100;
            updateTankUI();
        }
    }, 100);
}

function updateTankUI() {
    const levelRect = document.getElementById('tankLevel');
    const maxHeight = 120; // Matches the SVG height of the tank
    const currentHeight = (tankLevelPercent / 100) * maxHeight;
    
    levelRect.setAttribute('height', currentHeight);
    levelRect.setAttribute('y', 270 - currentHeight); // 270 is the bottom of the tank
}

// --- TIMER & ALARM LOGIC ---
function startTimer() {
    startTime = Date.now();
    timerInterval = setInterval(() => {
        elapsedSeconds = (Date.now() - startTime) / 1000;
        updateTimerDisplay();

        // SIMULATION: Trigger alarm if running/holding for > 10s
        if (elapsedSeconds > 10 && !alarmTriggered) {
            triggerRandomAlarm();
        }
    }, 100);
}

function updateTimerDisplay() {
    const unit = document.getElementById('unitSelector').value;
    const display = document.getElementById('timerDisplay');
    let value = elapsedSeconds;

    if (unit === 'm') value = elapsedSeconds / 60;
    if (unit === 'h') value = elapsedSeconds / 3600;

    display.innerText = `Duration: ${value.toFixed(2)}${unit}`;
}

function triggerRandomAlarm() {
    alarmTriggered = true;
    const fault = possibleFaults[Math.floor(Math.random() * possibleFaults.length)];
    const time = new Date().toLocaleTimeString();
    
    document.getElementById('alarmAlert').style.display = 'block';

    const tableBody = document.querySelector('#alarmTable tbody');
    const row = tableBody.insertRow(0);
    row.innerHTML = `<td>${time}</td><td class="critical">${fault.severity}</td><td>${fault.msg}</td>`;

    logEvent(`ALARM TRIGGERED: ${fault.msg}`);
}

function logEvent(msg) {
    const logList = document.getElementById('logList');
    const time = new Date().toLocaleTimeString();
    const newLog = document.createElement('li');
    newLog.innerText = `[${time}] ${msg}`;
    logList.prepend(newLog);
}