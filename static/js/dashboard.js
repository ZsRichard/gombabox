// Dashboard.js - Frontend logic for GombaBox
// Handles API communication, data visualization, and user interactions

const API_BASE = '/api';
const REFRESH_INTERVAL = 5000; // 5 seconds
const CHART_MAX_POINTS = 500; // Increased for handling larger time ranges

// Chart instances
let tempChart = null;
let humidityChart = null;
let co2Chart = null;
let lightChart = null;
let coverageChart = null;

// Current time range setting (in hours)
let currentTimeRange = 1;

// Data storage
let sensorHistory = {
    timestamps: [],
    temp: [],
    hum: [],
    co2: [],
    light: [],
    coverage: []
};

const SETTINGS_SCHEMA = [
    { key: 'target_temp', step: '0.1' },
    { key: 'temp_hysteresis', step: '0.1' },
    { key: 'target_humidity', step: '0.1' },
    { key: 'humidity_hysteresis', step: '0.1' },
    { key: 'humidity_pulse_duration_s', step: '1' },
    { key: 'humidity_pulse_cooldown_s', step: '1' },
    { key: 'co2_pulse_threshold_ppm', step: '1' },
    { key: 'co2_pulse_duration_s', step: '1' },
    { key: 'co2_pulse_cooldown_s', step: '1' },
    { key: 'co2_auto_vent_interval_s', step: '1' },
    { key: 'light_on_hour', step: '1' },
    { key: 'light_off_hour', step: '1' },
    { key: 'fan_cycle_on', step: '1' },
    { key: 'fan_cycle_off', step: '1' },
    { key: 'camera_interval', step: '1' },
    { key: 'camera_light_lead_seconds', step: '0.1' }
];

/**
 * Initialize application on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing GombaBox Dashboard...');
    
    // Set up time range selector listeners
    setupTimeRangeSelector();
    
    initializeCharts();
    loadInitialData();
    startAutoRefresh();
    loadControls();
    loadSettings();
    loadGrowthPhase();
    initializeDatabaseTab();
});

let dbTables = {};
let dbState = {
    table: null,
    limit: 50,
    offset: 0,
    total: 0
};
let dbEditContext = null;
let dbEditModal = null;

function initializeDatabaseTab() {
    const tableSelect = document.getElementById('db-table-select');
    const limitSelect = document.getElementById('db-table-limit');
    const refreshBtn = document.getElementById('db-refresh-btn');
    const prevBtn = document.getElementById('db-prev-btn');
    const nextBtn = document.getElementById('db-next-btn');
    const saveBtn = document.getElementById('db-save-btn');
    const modalElement = document.getElementById('db-edit-modal');

    if (!tableSelect || !limitSelect || !refreshBtn || !prevBtn || !nextBtn || !saveBtn || !modalElement) {
        return;
    }

    dbEditModal = new bootstrap.Modal(modalElement);

    tableSelect.addEventListener('change', () => {
        dbState.table = tableSelect.value;
        dbState.offset = 0;
        loadDatabaseRows();
    });

    limitSelect.addEventListener('change', () => {
        dbState.limit = Number(limitSelect.value);
        dbState.offset = 0;
        loadDatabaseRows();
    });

    refreshBtn.addEventListener('click', () => loadDatabaseRows());

    prevBtn.addEventListener('click', () => {
        dbState.offset = Math.max(0, dbState.offset - dbState.limit);
        loadDatabaseRows();
    });

    nextBtn.addEventListener('click', () => {
        const nextOffset = dbState.offset + dbState.limit;
        if (nextOffset < dbState.total) {
            dbState.offset = nextOffset;
            loadDatabaseRows();
        }
    });

    saveBtn.addEventListener('click', saveDatabaseRow);

    loadDatabaseTables();
}

function setDatabaseAlert(message, isError = false) {
    const alertEl = document.getElementById('db-alert');
    if (!alertEl) {
        return;
    }

    if (!message) {
        alertEl.style.display = 'none';
        alertEl.textContent = '';
        return;
    }

    alertEl.style.display = 'block';
    alertEl.classList.toggle('alert-danger-custom', isError);
    alertEl.classList.toggle('alert-warning-custom', !isError);
    alertEl.textContent = message;
}

function loadDatabaseTables() {
    fetch(`${API_BASE}/db/tables`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                setDatabaseAlert(data.error, true);
                return;
            }

            dbTables = data.tables || {};
            const tableSelect = document.getElementById('db-table-select');
            if (!tableSelect) {
                return;
            }

            tableSelect.innerHTML = '';
            const tableNames = Object.keys(dbTables);
            tableNames.forEach(name => {
                const option = document.createElement('option');
                option.value = name;
                option.textContent = name;
                tableSelect.appendChild(option);
            });

            if (!dbState.table && tableNames.length > 0) {
                dbState.table = tableNames[0];
                tableSelect.value = dbState.table;
            }

            loadDatabaseRows();
        })
        .catch(error => {
            console.error('Database table fetch error:', error);
            setDatabaseAlert('Failed to load database tables.', true);
        });
}

function loadDatabaseRows() {
    if (!dbState.table) {
        return;
    }

    setDatabaseAlert('Loading data...');

    const params = new URLSearchParams({
        limit: dbState.limit,
        offset: dbState.offset
    });

    fetch(`${API_BASE}/db/${encodeURIComponent(dbState.table)}?${params.toString()}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                setDatabaseAlert(data.error, true);
                return;
            }

            dbState.total = Number(data.total) || 0;
            renderDatabaseTable(data);
            updateDatabasePager();
            setDatabaseAlert('');
        })
        .catch(error => {
            console.error('Database rows fetch error:', error);
            setDatabaseAlert('Failed to load database rows.', true);
        });
}

function renderDatabaseTable(data) {
    const headEl = document.getElementById('db-table-head');
    const bodyEl = document.getElementById('db-table-body');
    if (!headEl || !bodyEl) {
        return;
    }

    const columns = data.columns || [];
    const editable = data.editable || [];

    headEl.innerHTML = '';
    bodyEl.innerHTML = '';

    const headerRow = document.createElement('tr');
    columns.forEach(column => {
        const th = document.createElement('th');
        th.textContent = column;
        headerRow.appendChild(th);
    });

    const actionsTh = document.createElement('th');
    actionsTh.textContent = 'Actions';
    headerRow.appendChild(actionsTh);
    headEl.appendChild(headerRow);

    data.rows.forEach(row => {
        const tr = document.createElement('tr');
        columns.forEach(column => {
            const td = document.createElement('td');
            td.textContent = row[column] !== undefined && row[column] !== null ? row[column] : '';
            tr.appendChild(td);
        });

        const actionTd = document.createElement('td');
        const editBtn = document.createElement('button');
        editBtn.className = 'btn btn-sm btn-primary me-2';
        editBtn.textContent = 'Edit';
        editBtn.addEventListener('click', () => openEditModal(row, columns, editable, data.id_field));

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-sm btn-danger';
        deleteBtn.textContent = 'Delete';
        deleteBtn.addEventListener('click', () => deleteDatabaseRow(row, data.id_field));

        actionTd.appendChild(editBtn);
        actionTd.appendChild(deleteBtn);
        tr.appendChild(actionTd);
        bodyEl.appendChild(tr);
    });
}

function updateDatabasePager() {
    const pageInfo = document.getElementById('db-page-info');
    if (!pageInfo) {
        return;
    }

    const currentPage = Math.floor(dbState.offset / dbState.limit) + 1;
    const totalPages = Math.max(1, Math.ceil(dbState.total / dbState.limit));
    pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
}

function openEditModal(row, columns, editable, idField) {
    if (!dbEditModal) {
        return;
    }

    const formEl = document.getElementById('db-edit-form');
    if (!formEl) {
        return;
    }

    dbEditContext = {
        id: row[idField],
        idField,
        table: dbState.table,
        editable
    };

    formEl.innerHTML = '';
    editable.forEach(field => {
        const wrapper = document.createElement('div');
        wrapper.className = 'mb-3';

        const label = document.createElement('label');
        label.className = 'form-label';
        label.textContent = field;
        label.setAttribute('for', `db-edit-${field}`);

        const input = document.createElement('input');
        input.className = 'form-control';
        input.id = `db-edit-${field}`;
        input.value = row[field] !== undefined && row[field] !== null ? row[field] : '';

        wrapper.appendChild(label);
        wrapper.appendChild(input);
        formEl.appendChild(wrapper);
    });

    dbEditModal.show();
}

function saveDatabaseRow() {
    if (!dbEditContext) {
        return;
    }

    const payload = {};
    dbEditContext.editable.forEach(field => {
        const input = document.getElementById(`db-edit-${field}`);
        if (input) {
            payload[field] = input.value;
        }
    });

    fetch(`${API_BASE}/db/${encodeURIComponent(dbEditContext.table)}/${encodeURIComponent(dbEditContext.id)}`,
        {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }
    )
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                setDatabaseAlert(data.error, true);
                return;
            }

            dbEditModal.hide();
            loadDatabaseRows();
        })
        .catch(error => {
            console.error('Database update error:', error);
            setDatabaseAlert('Failed to update row.', true);
        });
}

function deleteDatabaseRow(row, idField) {
    const rowId = row[idField];
    if (!confirm(`Delete row ${rowId}? This cannot be undone.`)) {
        return;
    }

    fetch(`${API_BASE}/db/${encodeURIComponent(dbState.table)}/${encodeURIComponent(rowId)}`,
        { method: 'DELETE' }
    )
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                setDatabaseAlert(data.error, true);
                return;
            }

            loadDatabaseRows();
        })
        .catch(error => {
            console.error('Database delete error:', error);
            setDatabaseAlert('Failed to delete row.', true);
        });
}

/**
 * Sort sensorHistory arrays by timestamp chronologically
 * Maintains correspondence between timestamps and their data values
 */
function sortSensorHistoryByTimestamp() {
    // Create array of indices
    const indices = Array.from({length: sensorHistory.timestamps.length}, (_, i) => i);
    
    // Sort indices based on timestamps
    indices.sort((a, b) => {
        const timeA = new Date(sensorHistory.timestamps[a]);
        const timeB = new Date(sensorHistory.timestamps[b]);
        return timeA - timeB;
    });
    
    // Reorder all arrays based on sorted indices
    const sortedData = {
        timestamps: indices.map(i => sensorHistory.timestamps[i]),
        temp: indices.map(i => sensorHistory.temp[i]),
        hum: indices.map(i => sensorHistory.hum[i]),
        co2: indices.map(i => sensorHistory.co2[i]),
        light: indices.map(i => sensorHistory.light[i]),
        coverage: indices.map(i => sensorHistory.coverage[i])
    };
    
    // Replace with sorted data
    sensorHistory = sortedData;
}

/**
 * Set up time range selector button listeners
 */
function setupTimeRangeSelector() {
    const timeRangeButtons = document.querySelectorAll('input[name="time-range"]');
    timeRangeButtons.forEach(button => {
        button.addEventListener('change', function(e) {
            currentTimeRange = parseInt(this.value);
            console.log('Time range changed to:', currentTimeRange, 'hours');
            loadHistoricalData();
        });
    });
}

/**
 * Load historical sensor data for the selected time range
 */
function loadHistoricalData() {
    // Fetch both measurements and camera captures
    Promise.all([
        fetch(`${API_BASE}/measurements/history?hours=${currentTimeRange}`).then(r => r.json()),
        fetch(`${API_BASE}/camera/history?hours=${currentTimeRange}`).then(r => r.json())
    ])
    .then(([measureData, cameraData]) => {
        if (measureData.error) {
            console.error('Error fetching measurements:', measureData.error);
            updateChartDataInfo(`Error loading data: ${measureData.error}`);
            return;
        }

        // Clear existing history
        sensorHistory = {
            timestamps: [],
            temp: [],
            hum: [],
            co2: [],
            light: [],
            coverage: []
        };

        // Process measurements from the API
        if (measureData.measurements && measureData.measurements.length > 0) {
            measureData.measurements.forEach(m => {
                sensorHistory.timestamps.push(m.time);
                sensorHistory.temp.push(parseFloat(m.temp));
                sensorHistory.hum.push(parseFloat(m.hum));
                sensorHistory.co2.push(parseInt(m.co2) || 0);
                sensorHistory.light.push(parseFloat(m.light) || 0);
            });
        }

        // Process camera captures for coverage data
        if (cameraData.captures && cameraData.captures.length > 0) {
            cameraData.captures.forEach(c => {
                // Find the corresponding timestamp in the history or add it
                const timestamp = c.time;
                let timestampIndex = sensorHistory.timestamps.indexOf(timestamp);
                
                // If the timestamp doesn't exist in measurements, add it
                if (timestampIndex === -1) {
                    sensorHistory.timestamps.push(timestamp);
                    sensorHistory.temp.push(null);
                    sensorHistory.hum.push(null);
                    sensorHistory.co2.push(null);
                    sensorHistory.light.push(null);
                    timestampIndex = sensorHistory.timestamps.length - 1;
                }
                
                // Add or update coverage for this timestamp
                sensorHistory.coverage[timestampIndex] = parseFloat(c.analysis) || 0;
            });
            
            // Ensure coverage array has the same length as timestamps
            while (sensorHistory.coverage.length < sensorHistory.timestamps.length) {
                sensorHistory.coverage.push(null);
            }
        }

        // Sort all data by timestamp to fix chronological order
        // This is necessary because camera captures may have been appended out of order
        sortSensorHistoryByTimestamp();

        console.log(`Loaded ${sensorHistory.timestamps.length} measurements and ${cameraData.captures ? cameraData.captures.length : 0} camera captures for ${measureData.hours} hours`);
        updateChartDataInfo(`${sensorHistory.timestamps.length} data points loaded (${measureData.hours} hour${measureData.hours !== 1 ? 's' : ''})`);
        updateCharts();
    })
    .catch(error => {
        console.error('Fetch error:', error);
        updateChartDataInfo('Failed to load data');
    });
}
function updateChartDataInfo(message) {
    const infoEl = document.getElementById('chart-data-info');
    if (infoEl) {
        infoEl.textContent = message;
    }
}

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

    // Temperature Chart
    const tempCtx = document.getElementById('temp-chart');
    if (tempCtx) {
        tempChart = new Chart(tempCtx, {
            type: 'line',
            data: {
                labels: sensorHistory.timestamps,
                datasets: [{
                    label: 'Temperature (°C)',
                    data: sensorHistory.temp,
                    borderColor: '#e74c3c',
                    backgroundColor: 'rgba(231, 76, 60, 0.1)',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                ...chartOptions,
                scales: {
                    y: {
                        beginAtZero: false,
                        title: { display: true, text: 'Temperature (°C)' }
                    }
                }
            }
        });
    }

    // Humidity Chart
    const humCtx = document.getElementById('humidity-chart');
    if (humCtx) {
        humidityChart = new Chart(humCtx, {
            type: 'line',
            data: {
                labels: sensorHistory.timestamps,
                datasets: [{
                    label: 'Humidity (%)',
                    data: sensorHistory.hum,
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
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
                        title: { display: true, text: 'Humidity (%)' }
                    }
                }
            }
        });
    }

    // CO₂ Chart
    const co2Ctx = document.getElementById('co2-chart');
    if (co2Ctx) {
        co2Chart = new Chart(co2Ctx, {
            type: 'line',
            data: {
                labels: sensorHistory.timestamps,
                datasets: [{
                    label: 'CO₂ (ppm)',
                    data: sensorHistory.co2,
                    borderColor: '#f39c12',
                    backgroundColor: 'rgba(243, 156, 18, 0.1)',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                ...chartOptions,
                scales: {
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'CO₂ (ppm)' }
                    }
                }
            }
        });
    }

    // Light Chart
    const lightCtx = document.getElementById('light-chart');
    if (lightCtx) {
        lightChart = new Chart(lightCtx, {
            type: 'line',
            data: {
                labels: sensorHistory.timestamps,
                datasets: [{
                    label: 'Light (lux)',
                    data: sensorHistory.light,
                    borderColor: '#2ecc71',
                    backgroundColor: 'rgba(46, 204, 113, 0.1)',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                ...chartOptions,
                scales: {
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Light (lux)' }
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
                    tension: 0.4,
                    spanGaps: true
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
    fetch(`${API_BASE}/camera/latest`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                return;
            }

            const coveragePercent = parseFloat(data.analysis || 0) || 0;

            // Update image
            if (data.url) {
                document.getElementById('latest-capture').src = data.url;
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
 * Refresh all relay states to keep UI in sync
 */
function refreshRelayStates() {
    document.querySelectorAll('.relay-toggle').forEach(toggle => {
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
    Promise.all([
        fetch(`${API_BASE}/settings`).then(response => response.json()),
        fetch(`${API_BASE}/settings/descriptions`).then(response => response.json())
    ])
        .then(([settingsData, descriptionsData]) => {
            if (settingsData.error) return;
            const descriptions = descriptionsData && !descriptionsData.error ? descriptionsData : {};

            let settingsHtml = '';
            SETTINGS_SCHEMA.forEach(({ key, step }) => {
                if (!(key in settingsData)) {
                    return;
                }

                const value = settingsData[key];
                const description = descriptions[key] || '';
                const labelText = formatSettingLabel(key);
                const infoIconHtml = description
                    ? `<i class="fas fa-circle-info ms-1 text-muted" title="${escapeHtml(description)}"></i>`
                    : '';
                settingsHtml += `
                    <div class="mb-3">
                        <label for="setting-${key}" class="form-label">
                            ${labelText}${infoIconHtml}
                        </label>
                        <input type="number" class="form-control" 
                               id="setting-${key}"
                               value="${value}"
                               step="${step}">
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

    function escapeHtml(value) {
        return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

/**
 * Load growth phase
 */
function loadGrowthPhase() {
    fetch(`${API_BASE}/phase`)
        .then(response => response.json())
        .then(data => {
            if (data.error) return;
            const select = document.getElementById('growth-phase');
            if (select && data.phase) {
                select.value = data.phase;
            }
        })
        .catch(error => console.error('Phase error:', error));
}

/**
 * Save growth phase
 */
function saveGrowthPhase() {
    const select = document.getElementById('growth-phase');
    if (!select) {
        return;
    }

    fetch(`${API_BASE}/phase`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ phase: select.value })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert('Error: ' + data.error);
            return;
        }
        alert('Phase updated successfully!');
    })
    .catch(error => {
        alert('Error updating phase: ' + error);
    });
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
    loadSensorData(); // Update current readings in top boxes
    loadHistoricalData(); // Load historical data for charts based on current time range
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
 * Restart system service
 */
function restartSystem() {
    if (!confirm('Restart the gombabox service now?')) {
        return;
    }

    fetch(`${API_BASE}/restart`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                alert('Error: ' + data.error);
                return;
            }
            alert('Service restart requested. The UI may briefly disconnect.');
            setTimeout(checkSystemStatus, 5000);
        })
        .catch(() => {
            alert('Restart requested. Connection may drop while the service restarts.');
            setTimeout(checkSystemStatus, 8000);
        });
}

/**
 * Capture image now
 */
function captureNow() {
    const button = event.target.closest('button');
    const originalText = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Capturing...';
    
    fetch(`${API_BASE}/camera/capture`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                alert('Error: ' + data.error);
            } else {
                alert(`Image captured! Coverage: ${data.coverage.toFixed(2)}%`);
                loadCameraData();
            }
        })
        .catch(error => {
            alert('Capture error: ' + error);
        })
        .finally(() => {
            button.disabled = false;
            button.innerHTML = originalText;
        });
}

/**
 * Update all charts
 */
function updateCharts() {
    if (tempChart) {
        tempChart.data.labels = sensorHistory.timestamps;
        tempChart.data.datasets[0].data = sensorHistory.temp;
        tempChart.update('none'); // Don't animate
    }

    if (humidityChart) {
        humidityChart.data.labels = sensorHistory.timestamps;
        humidityChart.data.datasets[0].data = sensorHistory.hum;
        humidityChart.update('none');
    }

    if (co2Chart) {
        co2Chart.data.labels = sensorHistory.timestamps;
        co2Chart.data.datasets[0].data = sensorHistory.co2;
        co2Chart.update('none');
    }

    if (lightChart) {
        lightChart.data.labels = sensorHistory.timestamps;
        lightChart.data.datasets[0].data = sensorHistory.light;
        lightChart.update('none');
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
        loadSensorData(); // Update current readings and add latest to history
        loadCameraData();
        checkSystemStatus();
        refreshRelayStates();
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
