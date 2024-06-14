import {Component} from "/common/lib/component.js";
import {MdApp, MdCard, MdDialog, StdDialog} from "/common/lib/material.js";

const delay = ms => new Promise(res => setTimeout(res, ms));

const medium_table = {
  0: "Other",
  1: "Oil",
  2: "Electricity",
  3: "Gas",
  4: "Heat",
  5: "Steam",
  6: "Hot Water",
  7: "Water",
  8: "H.C.A.",
}

function pad2(num) {
  return ("0" + num).toString().slice(-2)
}

function pad4(num) {
  return ("000" + num).toString().slice(-4)
}

function datestr(ts) {
  if (!ts) return "";
  let date = new Date(ts * 1000);
  let year = pad4(date.getFullYear());
  let month = pad2(date.getMonth() + 1);
  let day = pad2(date.getDate());
  let hours = pad2(date.getHours());
  let mins = pad2(date.getMinutes());
  let secs = pad2(date.getSeconds());
  return `${year}-${month}-${day} ${hours}:${mins}:${secs}`;
}

class MeterApp extends MdApp {
  onconnected() {
    this.monitor_updates();
    this.attach(this.ondownload, "click", "#download");
  }

  ondownload(e) {
    let url = this.database?.software;
    if (url) window.open(url);
  }

  async monitor_updates() {
    let seq = 0;
    while (true) {
      let r = await fetch(`/meterman/state?seq=${seq}`);
      if (r.status == 304) {
        continue;
      } else if (r.status == 200) {
        let state = await r.json();
        if (state.seq != seq) {
          seq = state.seq;
          this.database_update(state);
        }
      } else {
        await delay(30000);
      }
    }
  }

  select(gwid) {
    this.current = gwid;
    let gw = this.current && this.database.gateways[this.current];
    this.find("#gateway").update(gw);
    this.find("#gateways").update(this.database);
  }

  database_update(state) {
    this.database = state;
    this.find("#gateways").update(state);
    let gw = this.current && state.gateways[this.current];
    if (!gw) this.current = undefined;
    this.find("#gateway").update(gw);
  }

  render() {
    return `
      <md-toolbar>
        <md-toolbar-logo></md-toolbar-logo>
        <div id="title">Meter Manager</div>
        <md-spacer></md-spacer>
        <md-icon-button id="download" icon="download"></md-icon-button>
      </md-toolbar>

      <md-content>
        <div id="cols">
          <meter-gateways id="gateways"></meter-gateways>
          <meter-gateway id="gateway"></meter-gateway>
        </div>
      </md-content>
    `;
  }

  static stylesheet() {
    return `
      $ #cols {
        display: flex;
        font-size: 16px;
      }
    `;
  }
}

Component.register(MeterApp);

class MeterGateways extends MdCard {
  onconnect() {
    this.attach(this.onclick, "click");
  }

  onclick(e) {
    let gw = e.target.getAttribute("gw");
    if (gw) this.match("meter-app").select(gw);
  }

  render() {
    let selected = this.match("meter-app").current;
    let h = new Array();
    h.push("<md-card-toolbar>Gateways</md-card-toolbar>");
    let gateways = this.state && this.state.gateways;
    if (gateways) {
      let gwlist = Object.values(gateways).sort((a, b) => b.ts - a.ts);
      for (let gw of gwlist) {
        let cls = "entry" + (gw.gw == selected ? " selected" : "");
         h.push(`<div class="${cls}" gw="${gw.gw}">${gw.gw}</div>`);
      }
    }
    return h.join("");
  }

  static stylesheet() {
    return `
      $ {
        min-width: 200px;
      }
      $ .entry {
        padding: 4px;
      }
      $ .selected {
        font-weight: bold;
      }
      $ .entry:hover {
        background-color: #eeeeee;
        cursor: pointer;
      }
    `;
  }
}

Component.register(MeterGateways);

class MeterGateway extends MdCard {
  render() {
    let gw = this.state;
    if (!gw) return "";
    let upsince = datestr(gw.ts);
    let lastseen = datestr(gw.lastseen);

    let h = new Array();
    h.push(`<md-card-toolbar>Gateway ${gw.gw}</md-card-toolbar>`);

    h.push('<div>');
    h.push('<md-button id="reset" label="Reset"></md-button>');
    h.push('<md-button id="rescan" label="Rescan"></md-button>');
    h.push('<md-button id="sync" label="Sync"></md-button>');
    h.push('<md-button id="configure" label="Configure"></md-button>');
    h.push('<md-button id="upgrade" label="Upgrade"></md-button>');
    h.push('<md-button id="forget" label="Forget"></md-button>');
    h.push('<md-button id="command" label="Command"></md-button>');
    h.push('<md-button id="log" label="Log"></md-button>');
    h.push('</div>');

    h.push('<div class="info">');

    h.push('<div class="controller">');
    h.push(`<span class="title">Controller</span>`);
    h.push(`<table>`);
    h.push(`<tr><td>App</td><td>${gw.app || ""}</td></tr>`);
    h.push(`<tr><td>Version</td><td>${gw.version || ""}</td></tr>`);
    h.push(`<tr><td>Build date</td><td>${gw.build || ""}</td></tr>`);
    h.push(`<tr><td>Up since</td><td>${upsince}</td></tr>`);
    h.push(`<tr><td>Last seen</td><td>${lastseen}</td></tr>`);
    h.push(`<tr><td>Contol topic</td><td>${gw.control || ""}</td></tr>`);
    h.push(`<tr><td>PID</td><td>${gw.pid || ""}</td></tr>`);
    h.push(`<tr><td>OS</td><td>${gw.os || ""}</td></tr>`);
    h.push(`<tr><td>Model</td><td>${gw.model || ""}</td></tr>`);
    h.push(`<tr><td>Revision</td><td>${gw.revision || ""}</td></tr>`);
    h.push(`<tr><td>Serial no.</td><td>${gw.serial || ""}</td></tr>`);
    h.push(`</table>`);

    h.push('</div>');

    h.push('<div class="configuration">');
    h.push(`<span class="title">Configuration</span>`);
    h.push(`<pre>${gw.config || ""}</pre>`);
    h.push('</div>');

    h.push('</div>');

    h.push('</div>');

    h.push(`
      <div class="meters">
        <span class="title">Meters</span>
        <md-data-table id="metertab">
          <md-data-field field="meterid">Meter ID</md-data-field>
          <md-data-field field="manufacturer">Manufacturer</md-data-field>
          <md-data-field field="version">Version</md-data-field>
          <md-data-field field="type">Type</md-data-field>
          <md-data-field field="bus">Bus</md-data-field>
          <md-data-field field="address">Address</md-data-field>
          <md-data-field field="reading" style="text-align: right">Reading</md-data-field>
          <md-data-field field="time">Time</md-data-field>
        </md-data-table>
      </div>
    `);

    if (gw.console && gw.console.trim().length > 0) {
      h.push(`
        <div class="console">
          <span class="title">Console</span>
          <pre>${gw.console || ""}</pre>
        </div>
      `);
    }

    return h.join("");
  }

  onrendered() {
    if (!this.state) return;

    let meters = this.state.meters;
    if (meters) {
      let rows = new Array();
      for (let m of Object.values(meters)) {
        let type = m.type || m.medium;
        type = medium_table[type] || type || "";

        let reading = m.value;
        if (reading && m.unit) {
          reading = `${reading} ${m.unit}`;
        }
        if (!reading && m.reading) {
          let r = m.reading[0];
          reading = r.value;
          if (r.unit) reading = `${reading} ${r.unit}`;
        }

        let time = datestr(m.ts);
        rows.push({
          meterid: m.meterid,
          manufacturer: m.manufacturer,
          type: type,
          version: m.version,
          bus: `${m.bus || ""} ${m.device || ""}`,
          address: m.address,
          reading: reading,
          time:time,
        });
      }
      this.find("#metertab").update(rows);
    }

    this.attach(this.onreset, "click", "#reset");
    this.attach(this.onsync, "click", "#sync");
    this.attach(this.onupgrade, "click", "#upgrade");
    this.attach(this.onforget, "click", "#forget");
    this.attach(this.oncommand, "click", "#command");
    this.attach(this.onconfigure, "click", "#configure");
    this.attach(this.onrescan, "click", "#rescan");
    this.attach(this.onlog, "click", "#log");
  }

  async onreset(e) {
    let ok = await StdDialog.ask(
      "Reset", `Restart gateway ${this.state.gw}?`);
    if (ok) await this.command("reset");
  }

  async onlog(e) {
    await this.command("log");
  }

  async onsync(e) {
    let ok = await StdDialog.ask(
      "Sync", `Synchronze time on gateway ${this.state.gw}?`);
    if (ok) await this.command("timesync");
  }

  async onrescan(e) {
    let ok = await StdDialog.ask(
      "Sync", `Rescan for new meters on gateway ${this.state.gw}?`);
    if (ok) await this.command("rescan");
  }

  async onupgrade(e) {
    let ok = await StdDialog.ask(
      "Upgrade", `Upgrade software on gateway ${this.state.gw}?`);
    if (ok) await this.command("upgrade");
  }

  async onforget(e) {
    let ok = await StdDialog.ask(
      "Forget", `Forget gateway ${this.state.gw}?`);
    if (!ok) return;
    if (ok) await this.command("forget");
  }

  async oncommand(e) {
    let command = await StdDialog.prompt(
      `Send command to gateway ${this.state.gw}?`, "Command");
    if (command) await this.command("command", command);
  }

  async onconfigure(e) {
    let dialog = new ConfigDialog(this.state.config);
    let config = await dialog.show();
    if (config) await this.command("config", config);
  }

  async command(cmd, body) {
    let options = {method: "POST"};
    if (body) {
      options.body = body;
      options.headers = {"Content-Type": "text/plain"};
    }
    let r = await fetch(`/meterman/${cmd}?gw=${this.state.gw}`, options);
    if (!r.ok) console.log("Error", r);
  }

  static stylesheet() {
    return `
      $ {
        width: 100%;
      }
      $ .title {
        display:inline-block;
        font-size: 18px;
        font-weight: bold;
        padding: 12px 0 12px 4px;
      }
      $ .info {
        display: flex;
        flex-direction: row;
        gap: 4px;
        padding: 8px 0 8px 0;
      }
      $ .controller {
        flex: 1;
        padding: 8px;
        border: 2px solid #dddddd;
        font-size: 16px;
      }
      $ .configuration {
        flex: 1;
        padding: 4px;
        border: 2px solid #dddddd;
      }
      $ .configuration pre {
        font-size: 11px;
        margin: 2px;
        white-space: pre-wrap;
       }
      $ .controller td {
        padding: 8px 16px 0 0;
      }
      $ .meters {
        padding: 4px;
        border: 2px solid #dddddd;
      }
      $ .console {
        flex: 1;
        margin-top: 8px;
        padding: 4px 4px 4px;
        border: 2px solid #dddddd;
      }

      $ .console pre {
        font-size: 11px;
        white-space: pre-wrap;
      }
    `;
  }
}

Component.register(MeterGateway);

class ConfigDialog extends MdDialog {
  onconnected() {
    this.bind("textarea", "keydown", e => e.stopPropagation());
  }

  submit() {
    let config = this.find("textarea").value;
    try {
      JSON.parse(config);
    } catch(e) {
      this.find("#msg").innerText = e.message;
      return;
    }
    this.close(config);
  }

  render() {
    let config = this.state;
    return `
      <md-dialog-top>Configure gateway</md-dialog-top>
      <div id="content">
        <textarea
          rows="32"
          cols="80"
          spellcheck="false">${Component.escape(config)}</textarea>
          <div id="msg"></div>
      </div>
      <md-dialog-bottom>
        <button id="cancel">Cancel</button>
        <button id="submit">Configure</button>
      </md-dialog-bottom>
    `;
  }

  static stylesheet() {
    return `
      $ #content {
        display: flex;
        flex-direction: column;
        row-gap: 16px;
      }
    `;
  }
}

Component.register(ConfigDialog);

document.body.style = null;

