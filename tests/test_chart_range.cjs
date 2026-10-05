// Browser-independent regressions for date selection and chart request ordering.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function dashboard() {
    const elements = new Map();
    const presets = ['1', 'custom'].map(value => ({ value, addEventListener(event, callback) { this.change = callback; } }));
    const context = vm.createContext({
        console: { log() {}, warn() {}, error() {} }, URLSearchParams, setTimeout, clearTimeout,
        document: {
            addEventListener() {},
            getElementById(id) {
                if (!elements.has(id)) elements.set(id, { value: '', dataset: {}, checked: false,
                    classList: { add() {}, remove() {}, toggle(name, hidden) { this.hidden = hidden; } }, addEventListener() {} });
                return elements.get(id);
            },
            querySelectorAll(selector) { return selector.includes('time-range') ? presets : []; }
        }
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/dashboard.js'), 'utf8'), context);
    vm.runInContext('renderPhaseCalendar = () => {}; loadCoverageComparison = () => {}; updateCharts = () => { chartUpdates++; };', context);
    context.chartUpdates = 0;
    return { context, elements, presets, run: code => vm.runInContext(code, context) };
}

function response(body) {
    return { headers: { get: () => 'application/json' }, json: async () => body };
}

async function main() {
    const precise = dashboard();
    precise.run(`setDashboardDateInputValue(document.getElementById('chart-start-date'), '2026-06-03T09:15');
        setDashboardDateInputValue(document.getElementById('chart-end-date'), '2026-06-03T10:45');
        initializeChartTimeSelectors();`);
    assert.equal((precise.elements.get('chart-start-hour').innerHTML.match(/<option/g) || []).length, 24);
    assert.equal((precise.elements.get('chart-start-minute').innerHTML.match(/<option/g) || []).length, 60);
    assert.equal(precise.elements.get('chart-start-hour').value, '09');
    assert.equal(precise.elements.get('chart-end-minute').value, '45');
    precise.run(`document.getElementById('chart-start-minute').value = '30'; updateChartTime('start');
        chartCalendarSelection = 'start'; selectChartCalendarDay('2026-06-04');
        selectChartCalendarDay('2026-06-04');
        loadHistoricalData = () => { submitted = currentCustomRange; }; applyCustomChartRange();`);
    assert.equal(precise.context.submitted.start, '2026-06-04T09:30');
    assert.equal(precise.context.submitted.end, '2026-06-04T10:45');
    precise.run(`document.getElementById('chart-start-hour').value = '24'; updateChartTime('start');`);
    assert.equal(precise.elements.get('chart-start-date').dataset.isoValue, '2026-06-04T09:30');
    precise.run(`document.getElementById('chart-end-hour').value = '08'; updateChartTime('end');
        currentCustomRange = null; applyCustomChartRange();`);
    assert.equal(precise.run('currentCustomRange'), null, 'A reversed same-day range must not be applied');

    const visibility = dashboard();
    for (const phase of ['colonization', 'fruiting', 'stopped']) {
        visibility.run(`updateLatestCaptureCoverageVisibility('${phase}')`);
        assert.equal(visibility.elements.get('latest-capture-coverage').classList.hidden,
            phase !== 'colonization', `Latest coverage visibility for ${phase}`);
    }

    const selected = dashboard();
    selected.run(`setDashboardDateInputValue(document.getElementById('chart-start-date'), '2026-06-03T00:00');
        setDashboardDateInputValue(document.getElementById('chart-end-date'), '2026-06-05T23:59');
        loadHistoricalData = () => { submitted = currentCustomRange; }; applyCustomChartRange();`);
    assert.equal(selected.context.submitted.start, '2026-06-03T00:00');
    assert.equal(selected.context.submitted.end, '2026-06-05T23:59');
    assert.equal(selected.elements.get('time-custom').checked, true);
    selected.run('loadHistoryAvailability = () => Promise.resolve(null); setupTimeRangeSelector();');
    selected.presets[0].change.call(selected.presets[0]);
    selected.presets[1].change.call(selected.presets[1]);
    assert.equal(selected.elements.get('chart-start-date').dataset.isoValue, '2026-06-03T00:00');

    const invalid = dashboard();
    invalid.run(`document.getElementById('chart-start-date').dataset.isoValue = 'invalid';
        document.getElementById('chart-end-date').dataset.isoValue = '2026-06-05T23:59';
        loadHistoricalData = () => { throw new Error('Invalid date was submitted'); }; applyCustomChartRange();`);
    assert.equal(invalid.run('currentCustomRange'), null);

    const history = dashboard();
    const pending = [];
    history.context.fetch = url => new Promise(resolve => pending.push({ url, resolve }));
    const first = history.run('loadHistoricalData()');
    history.run('currentTimeRange = 24');
    const second = history.run('loadHistoricalData()');
    pending[2].resolve(response({ measurements: [{ time: '2026-06-05 12:00', temp: 22, hum: 85, co2: 800, light: 10 }],
        count: 1, returned_count: 1, hours: 24, mode: 'preset' }));
    pending[3].resolve(response({ captures: [{ time: '2026-06-05 12:00', analysis: null }], count: 1, fruiting_only: true }));
    await second;
    assert.equal(history.elements.get('coverage-chart-section').classList.hidden, true);
    assert.equal(history.run('sensorHistory.coverage[0]'), null);
    pending[0].resolve(response({ measurements: [], count: 0, hours: 1 }));
    pending[1].resolve(response({ captures: [], count: 0 }));
    await first;
    assert.equal(history.run('sensorHistory.temp[0]'), 22, 'An older response must not replace the selected range');
    assert.equal(history.context.chartUpdates, 1);

    history.context.fetch = async url => response(url.includes('measurements')
        ? { measurements: [], count: 0, hours: 24, start: '2026-06-18T00:00', end: '2026-06-20T23:59' }
        : { captures: [], count: 0 });
    await history.run('loadHistoricalData()');
    assert.equal(history.run('sensorHistory.timestamps.length'), 0, 'An empty result must clear old charts');
    assert.equal(history.elements.get('coverage-chart-section').classList.hidden, false);
    assert.match(history.elements.get('chart-range-info').textContent, /nincs mentett/);
    assert.equal(history.context.chartUpdates, 2);
    console.log('PASS: calendar ISO selection, custom range preservation, invalid dates, stale responses, empty chart clearing');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
