// Dashboard.js - Frontend logic for GombaBox
// Handles API communication, data visualization, and user interactions

const API_BASE = '/api';
const REFRESH_INTERVAL = 5000; // 5 seconds
const BACKGROUND_REFRESH_INTERVAL = 20000; // lower battery use when hidden
const OFFLINE_REFRESH_INTERVAL = 30000; // avoid aggressive retries when offline
const CHART_MAX_POINTS = 500; // Increased for handling larger time ranges

// Chart instances
let tempChart = null;
let humidityChart = null;
let co2Chart = null;
let lightChart = null;
let coverageChart = null;
let coverageTestChart = null;
let dataRefreshTimer = null;
let logsRefreshTimer = null;
let deferredInstallPrompt = null;
let coveragePreviewDebounceTimer = null;

// Current time range setting (in hours)
let currentTimeRange = 1;
let currentCustomRange = null;
let phasePeriods = [];
let phaseCalendarMonth = null;
let timelapseCalendarMonth = null;
let timelapseCalendarSelection = 'start';

const GROWTH_PHASE_COLORS = {
    colonization: 'rgba(46, 204, 113, 0.12)',
    fruiting: 'rgba(243, 156, 18, 0.12)'
};

const growthPhaseBackgroundPlugin = {
    id: 'growthPhaseBackground',
    beforeDatasetsDraw(chart) {
        if (chart.canvas.id === 'coverage-test-chart' || phasePeriods.length === 0) return;
        const labels = chart.data.labels || [];
        if (labels.length < 2) return;

        const firstTime = parseDashboardDate(labels[0]).getTime();
        const lastTime = parseDashboardDate(labels[labels.length - 1]).getTime();
        if (!Number.isFinite(firstTime) || !Number.isFinite(lastTime) || lastTime <= firstTime) return;

        const { ctx, chartArea } = chart;
        ctx.save();
        ctx.beginPath();
        ctx.rect(chartArea.left, chartArea.top, chartArea.right - chartArea.left, chartArea.bottom - chartArea.top);
        ctx.clip();

        phasePeriods.forEach(period => {
            const periodStart = parseDashboardDate(period.start).getTime();
            const periodEnd = period.end ? parseDashboardDate(period.end).getTime() : lastTime;
            const visibleStart = Math.max(firstTime, periodStart);
            const visibleEnd = Math.min(lastTime, periodEnd);
            if (visibleEnd <= visibleStart) return;

            const startRatio = (visibleStart - firstTime) / (lastTime - firstTime);
            const endRatio = (visibleEnd - firstTime) / (lastTime - firstTime);
            const left = chartArea.left + startRatio * (chartArea.right - chartArea.left);
            const right = chartArea.left + endRatio * (chartArea.right - chartArea.left);
            ctx.fillStyle = GROWTH_PHASE_COLORS[period.phase] || 'rgba(127, 140, 141, 0.10)';
            ctx.fillRect(left, chartArea.top, right - left, chartArea.bottom - chartArea.top);
        });
        ctx.restore();
    }
};

// Data storage
let sensorHistory = {
    timestamps: [],
    temp: [],
    hum: [],
    co2: [],
    light: [],
    coverage: [],
    coveragePreview: []
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
    { key: 'co2_auto_vent_interval_min', step: '1' },
    { key: 'light_on_hour', step: '1' },
    { key: 'light_off_hour', step: '1' },
    { key: 'camera_interval', step: '1' },
    { key: 'camera_light_lead_seconds', step: '0.1' },
    { key: 'sensor_sample_interval_s', step: '1' },
    { key: 'control_eval_interval_s', step: '1' }
];

/**
 * Initialize application on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing GombaBox Dashboard...');
    
    // Set up time range selector listeners
    setupTimeRangeSelector();
    initializeCustomChartRange();
    
    initializeCharts();
    loadInitialData();
    startAutoRefresh();
    loadControls();
    loadSettings();
    loadGrowthPhase();
    loadPhasePeriods();
    initializeDatabaseTab();
    initializeMediaExportDates();
    initializeCoveragePreviewInterval();
    initializeCoveragePreviewControls();
    updateNetworkStatusUI();
    initializePwaSupport();
});

function initializeMediaExportDates() {
    const startInput = document.getElementById('timelapse-start-date');
    const endInput = document.getElementById('timelapse-end-date');
    if (!startInput || !endInput) {
        return;
    }

    const now = new Date();
    const start = new Date(now);
    start.setDate(start.getDate() - 1);
    start.setSeconds(0, 0);
    now.setSeconds(0, 0);

    startInput.value = toDateTimeLocalInputValue(start);
    endInput.value = toDateTimeLocalInputValue(now);

    const previousMonthButton = document.getElementById('timelapse-calendar-prev');
    const nextMonthButton = document.getElementById('timelapse-calendar-next');
    if (previousMonthButton) previousMonthButton.addEventListener('click', () => shiftTimelapseCalendarMonth(-1));
    if (nextMonthButton) nextMonthButton.addEventListener('click', () => shiftTimelapseCalendarMonth(1));
    startInput.addEventListener('change', renderTimelapsePhaseCalendar);
    endInput.addEventListener('change', renderTimelapsePhaseCalendar);
}

function initializeCoveragePreviewInterval() {
    setCoveragePreviewIntervalFromHours(currentTimeRange);
}

function initializeCoveragePreviewControls() {
}

function useCoveragePreviewPreset(hours) {
    setCoveragePreviewIntervalFromHours(hours);
}

function setCoveragePreviewIntervalFromHours(hours) {
    const startInput = document.getElementById('coverage-preview-start');
    const endInput = document.getElementById('coverage-preview-end');
    if (!startInput || !endInput) {
        return;
    }

    const now = new Date();
    const start = new Date(now);
    start.setHours(start.getHours() - Math.max(1, Number(hours) || 1));
    start.setSeconds(0, 0);
    now.setSeconds(0, 0);

    startInput.value = toDateTimeLocalInputValue(start);
    endInput.value = toDateTimeLocalInputValue(now);
}

function toDateTimeLocalInputValue(dateObj) {
    const year = dateObj.getFullYear();
    const month = String(dateObj.getMonth() + 1).padStart(2, '0');
    const day = String(dateObj.getDate()).padStart(2, '0');
    const hours = String(dateObj.getHours()).padStart(2, '0');
    const minutes = String(dateObj.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function parseDashboardDate(value) {
    if (value instanceof Date) return value;
    return new Date(String(value).replace(' ', 'T'));
}

function initializeCustomChartRange() {
    const applyButton = document.getElementById('apply-chart-range');
    const previousMonthButton = document.getElementById('phase-calendar-prev');
    const nextMonthButton = document.getElementById('phase-calendar-next');
    setCustomChartIntervalFromHours(24);
    if (applyButton) applyButton.addEventListener('click', applyCustomChartRange);
    if (previousMonthButton) previousMonthButton.addEventListener('click', () => shiftPhaseCalendarMonth(-1));
    if (nextMonthButton) nextMonthButton.addEventListener('click', () => shiftPhaseCalendarMonth(1));
}

function setCustomChartIntervalFromHours(hours) {
    const startInput = document.getElementById('chart-start-date');
    const endInput = document.getElementById('chart-end-date');
    if (!startInput || !endInput) return;
    const end = new Date();
    const start = new Date(end);
    start.setHours(start.getHours() - Math.max(1, Number(hours) || 24));
    start.setSeconds(0, 0);
    end.setSeconds(0, 0);
    startInput.value = toDateTimeLocalInputValue(start);
    endInput.value = toDateTimeLocalInputValue(end);
}

function applyCustomChartRange() {
    const start = document.getElementById('chart-start-date')?.value;
    const end = document.getElementById('chart-end-date')?.value;
    if (!start || !end || parseDashboardDate(end) <= parseDashboardDate(start)) {
        updateHistoryDataInfo('Please select a valid custom start and end time.');
        return;
    }
    currentTimeRange = null;
    currentCustomRange = { start, end };
    phaseCalendarMonth = new Date(parseDashboardDate(start).getFullYear(), parseDashboardDate(start).getMonth(), 1);
    renderPhaseCalendar();
    const previewStart = document.getElementById('coverage-preview-start');
    const previewEnd = document.getElementById('coverage-preview-end');
    if (previewStart) previewStart.value = start;
    if (previewEnd) previewEnd.value = end;
    loadHistoricalData();
}

async function parseApiResponse(response) {
    const contentType = (response.headers.get('content-type') || '').toLowerCase();
    if (contentType.includes('application/json')) {
        return response.json();
    }

    const text = await response.text();
    const snippet = text.replace(/\s+/g, ' ').slice(0, 120);
    throw new Error(`Server returned non-JSON response (${response.status}): ${snippet}`);
}

async function postJson(path, payload) {
    const response = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    const data = await parseApiResponse(response);
    if (!response.ok) {
        const errorMessage = data && data.error ? data.error : `Request failed with status ${response.status}`;
        throw new Error(errorMessage);
    }

    if (data && data.error) {
        throw new Error(data.error);
    }

    return data;
}

function buildDateRangePayload() {
    const startInput = document.getElementById('timelapse-start-date');
    const endInput = document.getElementById('timelapse-end-date');
    if (!startInput || !endInput) {
        throw new Error('Date fields are not available on this page.');
    }

    const start = (startInput.value || '').trim();
    const end = (endInput.value || '').trim();
    if (!start || !end) {
        throw new Error('Please select both start and end times.');
    }

    const startDate = new Date(start);
    const endDate = new Date(end);

    if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
        throw new Error('Invalid date range. Please use valid start/end values.');
    }

    if (startDate > endDate) {
        throw new Error('Start time must be earlier than or equal to end time.');
    }

    const payload = { start, end };

    return payload;
}

function getEffectiveRefreshInterval() {
    if (!navigator.onLine) {
        return OFFLINE_REFRESH_INTERVAL;
    }

    return document.hidden ? BACKGROUND_REFRESH_INTERVAL : REFRESH_INTERVAL;
}

function runDataRefreshCycle() {
    if (!navigator.onLine) {
        updateNetworkStatusUI();
        return;
    }

    loadSensorData();
    loadCameraData();
    checkSystemStatus();
    refreshRelayStates();
}

function resetAutoRefreshTimers() {
    if (dataRefreshTimer) {
        clearInterval(dataRefreshTimer);
    }
    if (logsRefreshTimer) {
        clearInterval(logsRefreshTimer);
    }

    dataRefreshTimer = setInterval(runDataRefreshCycle, getEffectiveRefreshInterval());

    // Logs refresh less often when app is backgrounded or offline.
    const logsInterval = (!navigator.onLine || document.hidden) ? 120000 : 30000;
    logsRefreshTimer = setInterval(() => {
        if (navigator.onLine) {
            loadLogs();
        }
    }, logsInterval);
}

function updateNetworkStatusUI() {
    const networkAlert = document.getElementById('network-alert');
    if (networkAlert) {
        networkAlert.classList.toggle('d-none', navigator.onLine);
    }
}

function initializePwaSupport() {
    const installButton = document.getElementById('install-app-btn');

    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js').catch(err => {
                console.warn('Service worker registration failed:', err);
            });
        });
    }

    window.addEventListener('beforeinstallprompt', (event) => {
        event.preventDefault();
        deferredInstallPrompt = event;
        if (installButton) {
            installButton.classList.remove('d-none');
        }
        updatePwaDebugStatus();
    });

    if (installButton) {
        installButton.addEventListener('click', async () => {
            if (!deferredInstallPrompt) {
                return;
            }

            deferredInstallPrompt.prompt();
            await deferredInstallPrompt.userChoice;
            deferredInstallPrompt = null;
            installButton.classList.add('d-none');
        });
    }

    window.addEventListener('appinstalled', () => {
        deferredInstallPrompt = null;
        if (installButton) {
            installButton.classList.add('d-none');
        }
        updatePwaDebugStatus();
    });

    window.addEventListener('online', () => {
        updateNetworkStatusUI();
        loadInitialData();
        resetAutoRefreshTimers();
    });

    window.addEventListener('offline', () => {
        updateNetworkStatusUI();
        resetAutoRefreshTimers();
    });

    document.addEventListener('visibilitychange', resetAutoRefreshTimers);
}

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
        coverage: indices.map(i => sensorHistory.coverage[i]),
        coveragePreview: indices.map(i => sensorHistory.coveragePreview[i])
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
            const customControls = document.getElementById('custom-chart-range');
            if (this.value === 'custom') {
                if (customControls) customControls.classList.remove('d-none');
                setCustomChartIntervalFromHours(currentTimeRange || 24);
                return;
            }
            if (customControls) customControls.classList.add('d-none');
            currentTimeRange = parseInt(this.value, 10);
            currentCustomRange = null;
            console.log('Time range changed to:', currentTimeRange, 'hours');
            setCoveragePreviewIntervalFromHours(currentTimeRange);
            loadHistoricalData();
        });
    });
}

/**
 * Load historical sensor data for the selected time range
 */
function loadHistoricalData() {
    const rangeParams = new URLSearchParams();
    if (currentCustomRange) {
        rangeParams.set('start', currentCustomRange.start);
        rangeParams.set('end', currentCustomRange.end);
    } else {
        rangeParams.set('hours', currentTimeRange);
    }

    // Fetch both measurements and camera captures
    Promise.all([
        fetch(`${API_BASE}/measurements/history?${rangeParams}`).then(parseApiResponse),
        fetch(`${API_BASE}/camera/history?${rangeParams}`).then(parseApiResponse)
    ])
    .then(([measureData, cameraData]) => {
        if (measureData.error) {
            console.error('Error fetching measurements:', measureData.error);
            updateHistoryDataInfo(`Error loading data: ${measureData.error}`);
            return;
        }

        // Clear existing history
        sensorHistory = {
            timestamps: [],
            temp: [],
            hum: [],
            co2: [],
            light: [],
            coverage: [],
            coveragePreview: []
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
            while (sensorHistory.coveragePreview.length < sensorHistory.timestamps.length) {
                sensorHistory.coveragePreview.push(null);
            }
        }

        // Sort all data by timestamp to fix chronological order
        // This is necessary because camera captures may have been appended out of order
        sortSensorHistoryByTimestamp();

        const sampledNote = measureData.count > measureData.returned_count
            ? `; ${measureData.returned_count} evenly sampled for display`
            : '';
        const rangeLabel = measureData.mode === 'custom'
            ? `${formatPhaseDate(measureData.start)} – ${formatPhaseDate(measureData.end)}`
            : `${measureData.hours} hour${measureData.hours !== 1 ? 's' : ''}`;
        console.log(`Loaded ${sensorHistory.timestamps.length} chart points for ${rangeLabel}`);
        updateHistoryDataInfo(`${measureData.count} measurements, ${cameraData.count || 0} captures (${rangeLabel}${sampledNote})`);
        updateCharts();
        loadCoverageComparison();
    })
    .catch(error => {
        console.error('Fetch error:', error);
        updateHistoryDataInfo('Failed to load data');
    });
}

function updateHistoryDataInfo(message) {
    const infoEl = document.getElementById('chart-range-info');
    if (infoEl) infoEl.textContent = message;
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
    Chart.register(growthPhaseBackgroundPlugin);
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

    const coverageTestCtx = document.getElementById('coverage-test-chart');
    if (coverageTestCtx) {
        coverageTestChart = new Chart(coverageTestCtx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Original Coverage (%)',
                    data: [],
                    borderColor: '#9b59b6',
                    backgroundColor: 'rgba(155, 89, 182, 0.1)',
                    fill: false,
                    tension: 0.4,
                    spanGaps: true
                }, {
                    label: 'Recalculated Coverage (%)',
                    data: [],
                    borderColor: '#f39c12',
                    backgroundColor: 'rgba(243, 156, 18, 0.08)',
                    borderDash: [8, 4],
                    fill: false,
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
            updateGrowthPhaseUi(data.phase === 'stopped');
        })
        .catch(error => console.error('Phase error:', error));
}

function updateGrowthPhaseUi(isStopped) {
    const status = document.getElementById('growth-phase-status');
    if (status) {
        status.textContent = isStopped
            ? 'Stopped: sensor logging, automatic control and image capture are disabled.'
            : 'Active: sensor logging, automatic control and scheduled image capture are enabled.';
    }

    const captureButton = document.getElementById('capture-now-btn');
    if (captureButton) {
        captureButton.disabled = isStopped;
        captureButton.title = isStopped ? 'Image capture is disabled while the system is stopped.' : '';
    }

    document.querySelectorAll('.relay-toggle').forEach(toggle => {
        toggle.disabled = isStopped;
    });
}

function formatPhaseDate(value) {
    if (!value) return 'ongoing';
    const date = parseDashboardDate(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString([], {
        year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit'
    });
}

function phaseDisplayName(phase) {
    return phase === 'colonization' ? 'Incubation' : 'Fruiting';
}

function loadPhasePeriods() {
    fetch(`${API_BASE}/phase-periods`)
        .then(parseApiResponse)
        .then(data => {
            phasePeriods = data.periods || [];
            if (!phaseCalendarMonth) {
                const latestPeriod = phasePeriods[phasePeriods.length - 1];
                const calendarDate = latestPeriod
                    ? parseDashboardDate(latestPeriod.end || latestPeriod.start)
                    : new Date();
                phaseCalendarMonth = new Date(calendarDate.getFullYear(), calendarDate.getMonth(), 1);
            }
            if (!timelapseCalendarMonth) {
                timelapseCalendarMonth = new Date(phaseCalendarMonth.getFullYear(), phaseCalendarMonth.getMonth(), 1);
            }
            renderPhaseCalendar();
            renderTimelapsePhaseCalendar();
            updateCharts();
        })
        .catch(error => console.error('Phase period error:', error));
}

function periodsForCalendarDay(dayStart) {
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayEnd.getDate() + 1);
    return phasePeriods.filter(period => {
        const periodStart = parseDashboardDate(period.start);
        const periodEnd = period.end ? parseDashboardDate(period.end) : new Date(8640000000000000);
        return periodStart < dayEnd && periodEnd > dayStart;
    });
}

function renderPhaseCalendar() {
    renderPhaseCalendarGrid('phase-calendar-grid', 'phase-calendar-title', phaseCalendarMonth, false);
}

function renderTimelapsePhaseCalendar() {
    renderPhaseCalendarGrid('timelapse-calendar-grid', 'timelapse-calendar-title', timelapseCalendarMonth, true);
}

function renderPhaseCalendarGrid(gridId, titleId, calendarMonth, selectable) {
    const grid = document.getElementById(gridId);
    const title = document.getElementById(titleId);
    if (!grid || !title || !calendarMonth) return;

    title.textContent = calendarMonth.toLocaleDateString([], { year: 'numeric', month: 'long' });
    const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const firstOfMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth(), 1);
    const mondayOffset = (firstOfMonth.getDay() + 6) % 7;
    const firstCell = new Date(firstOfMonth);
    firstCell.setDate(firstCell.getDate() - mondayOffset);

    const cells = weekdays.map(day => `<div class="phase-calendar-weekday">${day}</div>`);
    for (let index = 0; index < 42; index += 1) {
        const date = new Date(firstCell);
        date.setDate(firstCell.getDate() + index);
        const periods = periodsForCalendarDay(date);
        const phases = new Set(periods.map(period => period.phase));
        let phaseClass = '';
        if (phases.size > 1) phaseClass = 'mixed';
        else if (phases.has('colonization')) phaseClass = 'incubation';
        else if (phases.has('fruiting')) phaseClass = 'fruiting';
        const outsideClass = date.getMonth() === calendarMonth.getMonth() ? '' : 'outside-month';
        const tooltip = periods.length
            ? periods.map(period => phaseDisplayName(period.phase)).join(' / ')
            : 'No recorded phase';
        const dateValue = toCalendarDateValue(date);
        const selectionClass = selectable ? timelapseCalendarSelectionClass(date) : '';
        const selectableAttributes = selectable
            ? ` role="button" tabindex="0" data-date="${dateValue}" onclick="selectTimelapseCalendarDay('${dateValue}')" onkeydown="handleTimelapseCalendarKey(event, '${dateValue}')"`
            : '';
        cells.push(
            `<div class="phase-calendar-day ${phaseClass} ${outsideClass} ${selectionClass}" title="${escapeHtml(tooltip)}"${selectableAttributes}>${date.getDate()}</div>`
        );
    }
    grid.innerHTML = cells.join('');
}

function toCalendarDateValue(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function timelapseCalendarSelectionClass(date) {
    const startValue = document.getElementById('timelapse-start-date')?.value;
    const endValue = document.getElementById('timelapse-end-date')?.value;
    const dayValue = toCalendarDateValue(date);
    const startDay = startValue ? startValue.slice(0, 10) : '';
    const endDay = endValue ? endValue.slice(0, 10) : '';
    if (dayValue === startDay) return 'selected-start';
    if (dayValue === endDay) return 'selected-end';
    if (startDay && endDay && dayValue > startDay && dayValue < endDay) return 'selected-range';
    return '';
}

function selectTimelapseCalendarDay(dateValue) {
    const startInput = document.getElementById('timelapse-start-date');
    const endInput = document.getElementById('timelapse-end-date');
    if (!startInput || !endInput) return;

    if (timelapseCalendarSelection === 'start') {
        startInput.value = `${dateValue}T00:00`;
        endInput.value = `${dateValue}T23:59`;
        timelapseCalendarSelection = 'end';
    } else {
        const startDay = startInput.value.slice(0, 10);
        if (dateValue < startDay) {
            startInput.value = `${dateValue}T00:00`;
            endInput.value = `${dateValue}T23:59`;
        } else {
            endInput.value = `${dateValue}T23:59`;
            timelapseCalendarSelection = 'start';
        }
    }
    renderTimelapsePhaseCalendar();
}

function handleTimelapseCalendarKey(event, dateValue) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    selectTimelapseCalendarDay(dateValue);
}

function shiftPhaseCalendarMonth(offset) {
    if (!phaseCalendarMonth) phaseCalendarMonth = new Date();
    phaseCalendarMonth = new Date(
        phaseCalendarMonth.getFullYear(),
        phaseCalendarMonth.getMonth() + offset,
        1
    );
    renderPhaseCalendar();
}

function shiftTimelapseCalendarMonth(offset) {
    if (!timelapseCalendarMonth) timelapseCalendarMonth = new Date();
    timelapseCalendarMonth = new Date(
        timelapseCalendarMonth.getFullYear(),
        timelapseCalendarMonth.getMonth() + offset,
        1
    );
    renderTimelapsePhaseCalendar();
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
        updateGrowthPhaseUi(select.value === 'stopped');
        alert(select.value === 'stopped'
            ? 'System stopped. The server remains available, but data collection and image capture are disabled.'
            : 'Phase updated successfully!');
        loadPhasePeriods();
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
    if (!navigator.onLine) {
        const statusBadge = document.getElementById('status-badge');
        const statusText = document.getElementById('system-status');

        if (statusBadge) {
            statusBadge.className = 'badge bg-warning ms-2';
            statusBadge.textContent = 'Offline';
        }
        if (statusText) {
            statusText.textContent = 'Network offline';
        }
        return;
    }

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
            const statusBadge = document.getElementById('status-badge');
            const statusText = document.getElementById('system-status');

            if (statusBadge) {
                statusBadge.className = 'badge bg-danger ms-2';
                statusBadge.textContent = 'Offline';
            }
            if (statusText) {
                statusText.textContent = 'Connection error';
            }
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

function setMediaExportStatus(message, isError = false) {
    const statusEl = document.getElementById('media-export-status');
    if (!statusEl) {
        return;
    }

    if (!message) {
        statusEl.classList.add('d-none');
        statusEl.textContent = '';
        return;
    }

    statusEl.textContent = message;
    statusEl.classList.remove('d-none');
    statusEl.classList.toggle('alert-danger-custom', isError);
    statusEl.classList.toggle('alert-info-custom', !isError);
}

function generateTimelapse() {
    const fpsInput = document.getElementById('timelapse-fps');
    const button = document.getElementById('generate-timelapse-btn');
    const resultEl = document.getElementById('timelapse-result');
    const linkEl = document.getElementById('timelapse-link');

    if (!fpsInput || !button || !resultEl || !linkEl) {
        return;
    }

    const fps = parseInt(fpsInput.value, 10);
    if (!Number.isInteger(fps) || fps < 1 || fps > 60) {
        setMediaExportStatus('Please set FPS to a value between 1 and 60.', true);
        return;
    }

    let payload;
    try {
        payload = buildDateRangePayload();
        payload.fps = fps;
    } catch (error) {
        setMediaExportStatus(`Timelapse setup error: ${error.message || error}`, true);
        return;
    }

    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
    resultEl.classList.add('d-none');
    setMediaExportStatus('Building timelapse. This can take a while for large image sets...');

    postJson('/camera/timelapse', payload)
        .then(data => {
            linkEl.href = data.video_url;
            resultEl.classList.remove('d-none');
            const stats = data.video_stats || {};
            const videoDuration = typeof stats.duration_seconds === 'number' ? stats.duration_seconds.toFixed(2) : data.duration_seconds;
            const videoFrames = stats.frame_count || data.frames;
            setMediaExportStatus(`Timelapse ready (${videoFrames} frames, ${videoDuration}s at ${data.fps} fps).`);
        })
        .catch(error => {
            setMediaExportStatus(`Timelapse error: ${error.message || error}`, true);
        })
        .finally(() => {
            button.disabled = false;
            button.innerHTML = originalHtml;
        });
}

function exportAnalyticsReport() {
    const button = document.getElementById('export-analytics-btn');
    const resultEl = document.getElementById('analytics-result');
    const svgLink = document.getElementById('analytics-svg-link');
    const measurementsLink = document.getElementById('analytics-measurements-link');
    const capturesLink = document.getElementById('analytics-captures-link');
    const summaryLink = document.getElementById('analytics-summary-link');

    if (!button || !resultEl || !svgLink || !measurementsLink || !capturesLink || !summaryLink) {
        return;
    }

    let payload;
    try {
        payload = buildDateRangePayload();
    } catch (error) {
        setMediaExportStatus(`Analytics setup error: ${error.message || error}`, true);
        return;
    }

    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Exporting...';
    resultEl.classList.add('d-none');
    setMediaExportStatus('Preparing analytics export...');

    postJson('/reports/analytics', payload)
        .then(data => {
            const files = data.files || {};
            svgLink.href = files.chart_svg_url || '#';
            measurementsLink.href = files.measurements_csv_url || '#';
            capturesLink.href = files.captures_csv_url || '#';
            summaryLink.href = files.summary_json_url || '#';
            resultEl.classList.remove('d-none');
            setMediaExportStatus('Analytics export ready. Open the generated files from the links below.');
        })
        .catch(error => {
            setMediaExportStatus(`Analytics export error: ${error.message || error}`, true);
        })
        .finally(() => {
            button.disabled = false;
            button.innerHTML = originalHtml;
        });
}

/**
 * Capture image now
 */
function captureNow(event) {
    const button = event.currentTarget;
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

function loadCoverageComparison() {
    const startInput = document.getElementById('coverage-preview-start');
    const endInput = document.getElementById('coverage-preview-end');
    const sampleInput = document.getElementById('coverage-preview-sample-hours');
    const topSlider = document.getElementById('coverage-crop-top');
    const leftSlider = document.getElementById('coverage-crop-left');
    const rightSlider = document.getElementById('coverage-crop-right');
    const bottomSlider = document.getElementById('coverage-crop-bottom');

    // Update displayed values but do not auto-trigger recalculation
    const updateSliderLabel = (slider, labelId) => {
        const el = document.getElementById(labelId);
        if (el && slider) el.textContent = slider.value;
    };

    if (topSlider) topSlider.addEventListener('input', () => updateSliderLabel(topSlider, 'coverage-crop-top-val'));
    if (leftSlider) leftSlider.addEventListener('input', () => updateSliderLabel(leftSlider, 'coverage-crop-left-val'));
    if (rightSlider) rightSlider.addEventListener('input', () => updateSliderLabel(rightSlider, 'coverage-crop-right-val'));
    if (bottomSlider) bottomSlider.addEventListener('input', () => updateSliderLabel(bottomSlider, 'coverage-crop-bottom-val'));

    // initialize displayed values
    if (topSlider) updateSliderLabel(topSlider, 'coverage-crop-top-val');
    if (leftSlider) updateSliderLabel(leftSlider, 'coverage-crop-left-val');
    if (rightSlider) updateSliderLabel(rightSlider, 'coverage-crop-right-val');
    if (bottomSlider) updateSliderLabel(bottomSlider, 'coverage-crop-bottom-val');
    const startValue = startInput ? startInput.value : '';
    const endValue = endInput ? endInput.value : '';
    const sampleEveryHours = sampleInput ? Math.max(1, Number(sampleInput.value) || 1) : 1;
    const topCrop = document.getElementById('coverage-crop-top') ? Number(document.getElementById('coverage-crop-top').value) : 20;
    const leftCrop = document.getElementById('coverage-crop-left') ? Number(document.getElementById('coverage-crop-left').value) : 20;
    const rightCrop = document.getElementById('coverage-crop-right') ? Number(document.getElementById('coverage-crop-right').value) : 10;
    const bottomCrop = document.getElementById('coverage-crop-bottom') ? Number(document.getElementById('coverage-crop-bottom').value) : 9;

    if (!startValue || !endValue) {
        updateChartDataInfo('Please choose both preview start and end times.');
        return;
    }

    const previewButton = document.getElementById('coverage-preview-btn');
    if (previewButton) {
        previewButton.disabled = true;
        previewButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Recalculating...';
    }

    // First request the compare summary which contains the selected max capture filename,
    // then explicitly request the preview for that filename to ensure deterministic preview.
    fetch(`${API_BASE}/camera/history/compare?start=${encodeURIComponent(startValue)}&end=${encodeURIComponent(endValue)}&sample_every_hours=${encodeURIComponent(sampleEveryHours)}&crop_top=${encodeURIComponent(topCrop)}&crop_left=${encodeURIComponent(leftCrop)}&crop_right=${encodeURIComponent(rightCrop)}&crop_bottom=${encodeURIComponent(bottomCrop)}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }

            const summary = data.summary || {};
            const maxFilename = summary.max_capture_filename || '';

            const previewUrlBase = `${API_BASE}/camera/history/preview-image?start=${encodeURIComponent(startValue)}&end=${encodeURIComponent(endValue)}&sample_every_hours=${encodeURIComponent(sampleEveryHours)}&crop_top=${encodeURIComponent(topCrop)}&crop_left=${encodeURIComponent(leftCrop)}&crop_right=${encodeURIComponent(rightCrop)}&crop_bottom=${encodeURIComponent(bottomCrop)}`;
            const previewUrl = maxFilename ? `${previewUrlBase}&filename=${encodeURIComponent(maxFilename)}` : previewUrlBase;

            return Promise.all([Promise.resolve(data), fetch(previewUrl).then(r => r.json())]);
        })
        .then(([data, previewImageData]) => {
            if (data.error) {
                updateChartDataInfo(`Preview failed: ${data.error}`);
                return;
            }

            const captures = Array.isArray(data.captures) ? data.captures : [];
            const labels = captures.map(capture => capture.time);
            const originalCoverage = captures.map(capture => {
                const value = Number(capture.original_analysis);
                return Number.isFinite(value) ? value : null;
            });
            const recalculatedCoverage = captures.map(capture => {
                const value = Number(capture.recalculated_analysis);
                return Number.isFinite(value) ? value : null;
            });

            if (coverageTestChart) {
                coverageTestChart.data.labels = labels;
                coverageTestChart.data.datasets[0].data = originalCoverage;
                coverageTestChart.data.datasets[1].data = recalculatedCoverage;
                coverageTestChart.update('none');
            }

            const previewImageEl = document.getElementById('coverage-preview-image');
            const previewMetaEl = document.getElementById('coverage-preview-image-meta');
            if (previewImageEl && previewImageData && previewImageData.image_data_url) {
                previewImageEl.src = previewImageData.image_data_url;
                if (previewMetaEl) {
                    previewMetaEl.textContent = `${previewImageData.filename || 'Preview'} · ${Number(previewImageData.original_coverage || 0).toFixed(2)}% -> ${Number(previewImageData.preprocessed_coverage || 0).toFixed(2)}%`;
                }
            } else if (previewMetaEl) {
                // Show debug info when image is not available
                if (previewImageData && previewImageData.debug) {
                    const dbg = previewImageData.debug;
                    previewMetaEl.textContent = `Preview unavailable — file: ${dbg.chosen_filename || 'n/a'}; exists: ${dbg.capture_exists === undefined ? 'unknown' : dbg.capture_exists}; path: ${dbg.capture_path || 'n/a'}`;
                } else {
                    previewMetaEl.textContent = 'No preview image available for this interval.';
                }
            }

            const summary = data.summary || {};
            const originalMax = Number(summary.original_max || summary.original_average || 0).toFixed(2);
            const recalculatedMax = Number(summary.recalculated_max || summary.recalculated_average || 0).toFixed(2);
            const maxFilename = summary.max_capture_filename || '';
            const maxTime = summary.max_capture_time || '';
            updateChartDataInfo(
                `Preview loaded for ${data.recalculated_count || 0} sampled captures between ${startValue} and ${endValue} (${sampleEveryHours}h sampling). Max: ${originalMax}% -> ${recalculatedMax}% ${maxFilename ? ` (file: ${maxFilename})` : ''}`
            );
        })
        .catch(error => {
            console.error('Preview fetch error:', error);
            updateChartDataInfo('Failed to load coverage preview');
        })
        .finally(() => {
            if (previewButton) {
                previewButton.disabled = false;
                previewButton.innerHTML = '<i class="fas fa-rotate"></i> Recalculate preview';
            }
        });
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
    resetAutoRefreshTimers();
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


