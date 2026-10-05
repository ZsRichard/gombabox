const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const elements = new Map();
const context = vm.createContext({ URLSearchParams, console, setTimeout, clearTimeout,
    document: { addEventListener() {}, getElementById(id) {
        if (!elements.has(id)) elements.set(id, { value: '', innerHTML: '', textContent: '' });
        return elements.get(id);
    } }
});
const run = code => vm.runInContext(code, context);
run(fs.readFileSync(path.join(__dirname, '../static/js/dashboard.js'), 'utf8'));
const response = data => ({ json: async () => data });

async function main() {
    run(`document.getElementById('logs-search').value = 'sensor';
        document.getElementById('logs-level').value = 'ERROR';
        document.getElementById('logs-sort').value = 'timestamp';
        document.getElementById('logs-direction').value = 'asc';
        document.getElementById('logs-limit').value = '50';`);
    let url;
    context.fetch = async request => { url = request; return response({ total: 1, logs: [
        { time: '2026-10-04 10:01:00', level: 'ERROR', source: 'sensors', message: '<script>sensor failed</script>' }
    ] }); };
    await run('loadLogs()');
    assert.match(url, /q=sensor/); assert.match(url, /level=ERROR/); assert.match(url, /direction=asc/);
    assert.equal(elements.get('logs-prev').disabled, true);
    assert.equal(elements.get('logs-next').disabled, true);
    assert.match(elements.get('logs-table').innerHTML, /&lt;script&gt;/);
    assert.ok(!elements.get('logs-table').innerHTML.includes('<script>'));
    const pending = [];
    context.fetch = () => new Promise(resolve => pending.push(resolve));
    const first = run('loadLogs()'); const second = run('loadLogs()');
    pending[1](response({ total: 0, logs: [] })); await second;
    pending[0](response({ total: 2, logs: [] })); await first;
    assert.match(elements.get('logs-page-info').textContent, /0 events/);
    run(`document.getElementById('db-search').value = 'fruiting';
        document.getElementById('db-filter-column').value = 'phase';
        document.getElementById('db-filter-op').value = 'eq';
        document.getElementById('db-filter-value').value = 'fruiting';
        document.getElementById('db-sort').value = 'id';
        dbState.table = 'camera_captures';
        setDatabaseAlert = () => {}; renderDatabaseTable = data => { rendered = data.rows; };
        updateDatabasePager = () => {};`);
    context.fetch = async request => { url = request; return response({ total: 0, rows: [] }); };
    await run('loadDatabaseRows()');
    assert.match(url, /q=fruiting/); assert.match(url, /filter_column=phase/); assert.match(url, /sort=id/);
    console.log('PASS: viewer filter queries, escaped logs, pagination, stale response guard');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
