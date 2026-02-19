// Dashboard.js - Frontend logic for GombaBox
// Handles API communication, data visualization, and user interactions

const API_BASE = '/api';
const REFRESH_INTERVAL = 5000; // 5 seconds
const CHART_MAX_POINTS = 20;

// Chart instances
let tempHumChart = null;
let co2LightChart = null;
let coverageChart = null;

// Data storage
let sensorHistory = {
    timestamps: [],
    temp: [],
    hum: [],
    co2: [],
    light: [],
    coverage: []
};

/**
 * Initialize application on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing GombaBox Dashboard...');
    initializeCharts();
    loadInitialData();
    startAutoRefresh();
    loadControls();
    loadSettings();
});

/**
 * Initialize all Chart.js instances
 */
function initializeCharts() {
    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: true,
                position: 'top',
            },
            filler: {
                propagate: true
            }
        },
        scales: {
            y: {
                beginAtZero: true
            }
        }
    };

    // Temperature & Humidity Chart
    const tempHumCtx = document.getElementById('temp-hum-chart');
    if (tempHumCtx) {
        tempHumChart = new Chart(tempHumCtx, {
            type: 'line',
            data: {
                labels: sensorHistory.timestamps,
                datasets: [
                    {
                        label: 'Temperature (°C)',
                        data: sensorHistory.temp,
                        borderColor: '#e74c3c',
                        backgroundColor: 'rgba(231, 76, 60, 0.1)',
                        tension: 0.4,
                        yAxisID: 'y'
                    },
                    {
                        label: 'Humidity (%)',
                        data: sensorHistory.hum,
                        borderColor: '#3498db',
                        backgroundColor: 'rgba(52, 152, 219, 0.1)',
                        tension: 0.4,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                ...chartOptions,
                scales: {
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: { display: true, text: 'Temperature (°C)' }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: { display: true, text: 'Humidity (%)' },
                        grid: { drawOnChartArea: false }
                    }
                }
            }
        });
    }

    // CO₂ & Light Chart
    const co2LightCtx = document.getElementById('co2-light-chart');
    if (co2LightCtx) {
        co2LightChart = new Chart(co2LightCtx, {
            type: 'line',
            data: {
                labels: sensorHistory.timestamps,
                datasets: [
                    {
                        label: 'CO₂ (ppm)',
                        data: sensorHistory.co2,
                        borderColor: '#f39c12',
                        backgroundColor: 'rgba(243, 156, 18, 0.1)',
                        tension: 0.4,
                        yAxisID: 'y'
                    },
                    {
                        label: 'Light (lux)',
                        data: sensorHistory.light,
                        borderColor: '#2ecc71',
                        backgroundColor: 'rgba(46, 204, 113, 0.1)',
                        tension: 0.4,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                ...chartOptions,
                scales: {
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: { display: true, text: 'CO₂ (ppm)' }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: { display: true, text: 'Light (lux)' },
                        grid: { drawOnChartArea: false }
                    }
                }
            }
        });
    }

    // Mycelium Coverage Chart
    const coverageCtx = document.getElementById('coverage-chart');
    if (coverageCtx) {
        coverageChart = new Chart(coverageCtx, {
            type: 'line',
            data: {
                labels: sensorHistory.timestamps,
                datasets: [{
                    label: 'Mycelium Coverage (%)',
                    data: sensorHistory.coverage,
                    borderColor: '#9b59b6',
                    backgroundColor: 'rgba(155, 89, 182, 0.1)',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                ...chartOptions,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        title: { display: true, text: 'Coverage (%)' }
                    }
                }
            }
        });
    }
}

/**
 * Load and display current sensor readings
 */
function loadSensorData() {
    fetch(`${API_BASE}/measurements/latest`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Error:', data.error);
                return;
            }

            const temperature = Number(data.temp);
            const humidity = Number(data.hum);
            const co2 = Number(data.co2);
            const light = Number(data.light);

            if (!Number.isFinite(temperature) || !Number.isFinite(humidity)) {
                return;
            }

            // Update sensor displays
            document.getElementById('temp-value').textContent = temperature.toFixed(1);
            document.getElementById('hum-value').textContent = humidity.toFixed(1);
            document.getElementById('co2-value').textContent = Number.isFinite(co2) ? co2 : '--';
            document.getElementById('light-value').textContent = Number.isFinite(light) ? light : '--';

            // Add to history
            const now = new Date().toLocaleTimeString();
            sensorHistory.timestamps.push(now);
            sensorHistory.temp.push(temperature);
            sensorHistory.hum.push(humidity);
            sensorHistory.co2.push(co2);
            sensorHistory.light.push(light);

            // Keep only last N points
            if (sensorHistory.timestamps.length > CHART_MAX_POINTS) {
                sensorHistory.timestamps.shift();
                sensorHistory.temp.shift();
                sensorHistory.hum.shift();
                sensorHistory.co2.shift();
                sensorHistory.light.shift();
            }

            updateCharts();
            updateTimestamp();
        })
        .catch(error => console.error('Fetch error:', error));
}

/**
 * Load latest camera capture and coverage analysis
 */
function loadCameraData() {
    fetch(`${API_BASE}/camera/captures?limit=1`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                return;
            }

            const captures = Array.isArray(data) ? data : (data.captures || []);
            if (captures.length === 0) {
                return;
            }

            const capture = captures[captures.length - 1];
            const coveragePercent = parseFloat(capture.analysis || capture.analysis_result) || 0;

            // Update image
            const imageUrl = capture.url || capture.image_path;
            if (imageUrl) {
                document.getElementById('latest-capture').src = imageUrl;
            }
            
            // Update coverage percentage and progress bar
            document.getElementById('coverage-percentage').textContent = 
                coveragePercent.toFixed(2) + '%';
            document.getElementById('coverage-bar').style.width = coveragePercent + '%';

            // Add to history
            sensorHistory.coverage.push(coveragePercent);
            if (sensorHistory.coverage.length > CHART_MAX_POINTS) {
                sensorHistory.coverage.shift();
            }

            updateCharts();
        })
        .catch(error => console.error('Camera fetch error:', error));
}

/**
 * Load relay controls
 */
function loadControls() {
    const relays = [
        { id: 1, name: 'Fan (Ventilation)', icon: 'fa-fan' },
        { id: 2, name: 'Humidifier (Mist)', icon: 'fa-water' },
        { id: 3, name: 'LED Light', icon: 'fa-lightbulb' }
    ];

    const controlsHtml = relays.map(relay => `
        <div class="relay-switch">
            <div class="relay-name">
                <i class="fas ${relay.icon}"></i> ${relay.name}
            </div>
            <div class="form-check form-switch">
                <input class="form-check-input relay-toggle" type="checkbox" 
                       id="relay-${relay.id}" data-relay-id="${relay.id}">
                <label class="form-check-label" for="relay-${relay.id}"></label>
            </div>
        </div>
    `).join('');

    document.getElementById('relay-controls').innerHTML = controlsHtml;

    // Add event listeners
    document.querySelectorAll('.relay-toggle').forEach(toggle => {
        toggle.addEventListener('change', function() {
            toggleRelay(this.dataset.relayId, this.checked);
        });
        // Load initial state
        loadRelayState(toggle.dataset.relayId, toggle);
    });
}

/**
 * Load relay state from API
 */
function loadRelayState(relayId, checkbox) {
    fetch(`${API_BASE}/relay/${relayId}`)
        .then(response => response.json())
        .then(data => {
            checkbox.checked = data.state === true || data.state == 1;
        })
        .catch(error => console.error('Relay state error:', error));
}

/**
 * Toggle relay on/off via API
 */
function toggleRelay(relayId, state) {
    fetch(`${API_BASE}/relay/${relayId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ state: state })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert('Error: ' + data.error);
        }
        console.log(`Relay ${relayId} set to ${state}`);
    })
    .catch(error => console.error('Relay toggle error:', error));
}

/**
 * Load system settings
 */
function loadSettings() {
    fetch(`${API_BASE}/settings`)
        .then(response => response.json())
        .then(data => {
            if (data.error) return;

            let settingsHtml = '';
            Object.entries(data).forEach(([key, value]) => {
                settingsHtml += `
                    <div class="mb-3">
                        <label for="setting-${key}" class="form-label">
                            ${formatSettingLabel(key)}
                        </label>
                        <input type="number" class="form-control" 
                               id="setting-${key}"
                               value="${value}"
                               step="0.1">
                        <button class="btn btn-sm btn-primary mt-2"
                                onclick="saveSetting('${key}')">
                            Save
                        </button>
                    </div>
                `;
            });

            document.getElementById('settings-form').innerHTML = settingsHtml;
        })
        .catch(error => console.error('Settings error:', error));
}

/**
 * Save setting to API
 */
function saveSetting(key) {
    const value = document.getElementById(`setting-${key}`).value;

    fetch(`${API_BASE}/settings/${key}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ value: value })
    })
    .then(response => response.json())
    .then(data => {
        alert('Setting saved successfully!');
    })
    .catch(error => {
        alert('Error saving setting: ' + error);
    });
}

/**
 * Load system logs
 */
function loadLogs() {
    fetch(`${API_BASE}/system/logs?limit=20`)
        .then(response => response.json())
        .then(data => {
            if (data.error) return;

            let logsHtml = '';
            data.forEach(log => {
                const timeText = log.time || log.timestamp || '';
                const Badge = getBadgeClass(log.level);
                logsHtml += `
                    <tr>
                        <td>${timeText}</td>
                        <td><span class="badge ${Badge}">${log.level}</span></td>
                        <td>${log.message}</td>
                    </tr>
                `;
            });

            document.getElementById('logs-table').innerHTML = logsHtml;
        })
        .catch(error => console.error('Logs error:', error));
}

/**
 * Load all initial data
 */
function loadInitialData() {
    loadSensorData();
    loadCameraData();
    loadLogs();
    checkSystemStatus();
}

/**
 * Check system status
 */
function checkSystemStatus() {
    fetch(`${API_BASE}/health`)
        .then(response => response.json())
        .then(data => {
            const statusBadge = document.getElementById('status-badge');
            const statusText = document.getElementById('system-status');

            if (data.status === 'ok') {
                statusBadge.className = 'badge bg-success ms-2';
                statusBadge.textContent = 'Online';
                statusText.textContent = data.background_running ? 'Running normally' : 'Idle';
            } else {
                statusBadge.className = 'badge bg-danger ms-2';
                statusBadge.textContent = 'Offline';
                statusText.textContent = 'System offline';
            }
        })
        .catch(error => {
            document.getElementById('status-badge').className = 'badge bg-danger ms-2';
            document.getElementById('system-status').textContent = 'Connection error';
        });
}

/**
 * Start system
 */
function startSystem() {
    fetch(`${API_BASE}/start`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            alert(data.message || 'System started');
            checkSystemStatus();
        })
        .catch(error => alert('Error: ' + error));
}

/**
 * Stop system
 */
function stopSystem() {
    if (confirm('Are you sure you want to stop the system?')) {
        fetch(`${API_BASE}/stop`, { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                alert(data.message || 'System stopped');
                checkSystemStatus();
            })
            .catch(error => alert('Error: ' + error));
    }
}

/**
 * Update all charts
 */
function updateCharts() {
    if (tempHumChart) {
        tempHumChart.data.labels = sensorHistory.timestamps;
        tempHumChart.data.datasets[0].data = sensorHistory.temp;
        tempHumChart.data.datasets[1].data = sensorHistory.hum;
        tempHumChart.update('none'); // Don't animate
    }

    if (co2LightChart) {
        co2LightChart.data.labels = sensorHistory.timestamps;
        co2LightChart.data.datasets[0].data = sensorHistory.co2;
        co2LightChart.data.datasets[1].data = sensorHistory.light;
        co2LightChart.update('none');
    }

    if (coverageChart) {
        coverageChart.data.labels = sensorHistory.timestamps;
        coverageChart.data.datasets[0].data = sensorHistory.coverage;
        coverageChart.update('none');
    }
}

/**
 * Update last update timestamp
 */
function updateTimestamp() {
    const now = new Date();
    document.getElementById('last-update').textContent = now.toLocaleTimeString();
}

/**
 * Start auto-refresh of data
 */
function startAutoRefresh() {
    setInterval(() => {
        loadSensorData();
        loadCameraData();
        checkSystemStatus();
    }, REFRESH_INTERVAL);

    // Refresh logs every 30 seconds
    setInterval(() => {
        loadLogs();
    }, 30000);
}

/**
 * Format setting labels from keys
 */
function formatSettingLabel(key) {
    return key
        .replace(/_/g, ' ')
        .split(' ')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

/**
 * Get badge CSS class for log level
 */
function getBadgeClass(level) {
    switch(level.toUpperCase()) {
        case 'INFO': return 'bg-info';
        case 'WARNING': return 'bg-warning';
        case 'ERROR': return 'bg-danger';
        case 'DEBUG': return 'bg-secondary';
        default: return 'bg-light text-dark';
    }
}
