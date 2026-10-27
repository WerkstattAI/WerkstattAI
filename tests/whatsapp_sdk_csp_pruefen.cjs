// Echtes öffentliches SDK aus lokalen Dateien; alle Browser-Netzaufrufe werden abgefangen.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const sdkOrdner = process.env.WERKSTATTAI_PRUEFSDK_ORDNER;
const playwright = process.env.WERKSTATTAI_PRUEFPLAYWRIGHT;
const chrome = process.env.WERKSTATTAI_PRUEFCHROME;
assert(sdkOrdner && playwright && chrome, 'Lokale SDK-Dateien, Playwright-Modul und Chrome-Pfad explizit angeben.');
const sdk = fs.readFileSync(path.join(sdkOrdner, 'meta-sdk-aktuell.js'));
const bundle = fs.readFileSync(path.join(sdkOrdner, 'meta-sdk-bundle.js'));
const {chromium} = require(playwright);
const quelle = spawnSync(process.env.WERKSTATTAI_PRUEFPYTHON || 'python', ['-c', `
import json, sys
sys.path.insert(0, 'tests')
from test_whatsapp_anschluss import AnschlussTests
fall = AnschlussTests()
try:
    fall.setUp()
    ausgabe = {}
    for name, pfad in [('anschluss', '/dashboard/whatsapp/verbinden'), ('dashboard', '/dashboard/settings')]:
        antwort = fall.client.get(pfad)
        assert antwort.status_code == 200
        ausgabe[name] = {'html': antwort.text, 'csp': antwort.headers['content-security-policy']}
    print(json.dumps(ausgabe))
finally:
    fall.doCleanups()
`], {cwd:path.resolve(__dirname,'..'), encoding:'utf8', env:{...process.env, APP_ENV:'test',
    DATABASE_URL:'', AUTH_SECRET:'synthetischer-browser-pruefschluessel', PYTHONUTF8:'1', PYTHONDONTWRITEBYTECODE:'1'}});
assert.equal(quelle.status, 0, 'Isolierte Testseite konnte nicht erzeugt werden: ' + quelle.stderr);
const seiten = JSON.parse(quelle.stdout);

(async()=>{
  const browser = await chromium.launch({headless:true, executablePath:chrome});
  try {
    const context = await browser.newContext({serviceWorkers:'block'});
    const aufrufe = [];
    let konfigurationAbgerufen = false;
    await context.route('**/*', async route=>{
      const url = route.request().url();
      aufrufe.push(url);
      const name = url === 'https://testserver/dashboard/whatsapp/verbinden' ? 'anschluss'
        : url === 'https://testserver/dashboard/settings' ? 'dashboard' : null;
      if (name) return route.fulfill({status:200, contentType:'text/html',
        headers:{'content-security-policy':seiten[name].csp}, body:seiten[name].html});
      if (url === 'https://connect.facebook.net/de_DE/sdk.js')
        return route.fulfill({status:200, contentType:'text/javascript', body:sdk});
      if (url.startsWith('https://connect.facebook.net/de_DE/bundle/sdk.js/'))
        return route.fulfill({status:200, contentType:'text/javascript', body:bundle});
      if (url.startsWith('https://connect.facebook.net/app_config/json/111/')) {
        konfigurationAbgerufen=true;
        return route.fulfill({status:200, contentType:'application/json',
          headers:{'access-control-allow-origin':'https://testserver'}, body:'{}'});
      }
      if (url === 'https://testserver/dashboard/whatsapp/verbinden/start')
        return route.fulfill({status:200, json:{kennung:'k'.repeat(43),zustand:'offen',meldung:'Synthetisch'}});
      return route.abort();
    });
    await context.addInitScript(()=>{
      window.verletzungen=[];
      document.addEventListener('securitypolicyviolation', e=>window.verletzungen.push({direktive:e.effectiveDirective,url:e.blockedURI}));
    });
    const page = await context.newPage();
    await page.goto('https://testserver/dashboard/whatsapp/verbinden');
    await page.waitForFunction(()=>document.getElementById('start')?.disabled === false);
    // FB.init hat den echten SDK-Abruf ausgelöst; die Antwort bleibt vollständig synthetisch.
    await page.waitForFunction(()=>performance.getEntriesByType('resource').some(e=>e.name.includes('/app_config/json/111/')));
    assert(konfigurationAbgerufen, 'Der SDK-Konfigurationsabruf muss die aktive CSP passieren.');
    assert.deepEqual(await page.evaluate(()=>verletzungen), [], 'SDK-Initialisierung verletzt die Anschluss-CSP.');
    await page.evaluate(()=>{
      const login=FB.login;
      FB.login=function(callback, optionen) { window.loginOptionen=optionen; return login.call(this,callback,optionen); };
    });
    const popupAnfrage = context.waitForEvent('request', {timeout:10000,
      predicate:r=>new URL(r.url()).pathname.endsWith('/dialog/oauth')});
    await page.click('#start');
    const weitergabe = new URL((await popupAnfrage).url());
    assert.equal(JSON.parse(weitergabe.searchParams.get('extras')).sessionInfoVersion,'3');
    const optionen=await page.evaluate(()=>loginOptionen);
    assert.equal(optionen.extras.sessionInfoVersion,'3');
    assert.equal(optionen.extras.featureType,'whatsapp_business_app_onboarding');
    assert.equal(optionen.extras.version,undefined);
    // Negativkontrollen: Inline-Skript ohne Nonce und fremder Ursprung bleiben gesperrt.
    await page.evaluate(()=>{
      const script=document.createElement('script');script.textContent='window.unerlaubt=true';document.head.appendChild(script);
      fetch('https://nicht-erlaubt.invalid/pruefung').catch(()=>{});
    });
    await page.waitForFunction(()=>verletzungen.some(e=>e.direktive==='script-src-elem') && verletzungen.some(e=>e.url.includes('nicht-erlaubt.invalid')));
    assert.equal(await page.evaluate(()=>window.unerlaubt),undefined);
    assert(!aufrufe.some(url=>url.includes('nicht-erlaubt.invalid')));
    const andere = await context.newPage();
    await andere.goto('https://testserver/dashboard/settings');
    await andere.evaluate(()=>fetch('https://connect.facebook.net/app_config/json/111/').catch(()=>{}));
    await andere.waitForFunction(()=>verletzungen.some(e=>e.direktive==='connect-src' && e.url.includes('connect.facebook.net')));
    assert(!seiten.dashboard.csp.includes('connect.facebook.net'));
    assert(!seiten.anschluss.csp.includes('*'));
    console.log(JSON.stringify({sdk_initialisiert:true, konfigurationsabruf_erlaubt:true,
      session_schema_angefordert:'3', session_schema_im_sdk_popup:'3', nonce_schutz:true, fremder_ursprung_gesperrt:true,
      uebriges_dashboard_unveraendert:true, browseraufrufe_abgefangen:aufrufe.length}));
  } finally { await browser.close(); }
})().catch(fehler=>{console.error(fehler);process.exitCode=1;});
