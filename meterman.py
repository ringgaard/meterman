# Copyright 2021 Ringgaard Research ApS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http:#www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import time
import paho.mqtt.client as mqtt
import threading

import sling
import sling.flags as flags
import sling.log as log
import sling.net

import lorawan

flags.define("--port",
             help="port number for the HTTP server",
             default=8080,
             type=int,
             metavar="PORT")

flags.define("--mqtt",
             help="MQTT server",
             default="vault.ringgaard.com",
             metavar="HOST")

flags.define("--history",
             help="Keep history of meter readings",
             default=False,
             action="store_true")

flags.define("--appdir",
             help="Application directory for upgrades",
             default="/var/data/metermon",
             metavar="PATH")

flags.define("--keys",
             help="File with encryption keys for meters",
             metavar="PATH")

# Parse command line flags.
flags.parse()

# Read meter encryption keys.
aeskeys = {}
if flags.arg.keys:
  with open(flags.arg.keys) as f:
    for line in f.readlines():
      line = line.strip()
      if len(line) == 0 or line[0] == '#': continue
      fields = line.split(' ')
      aeskeys[int(fields[0])] = fields[1]

# Initialize web server.
app = sling.net.HTTPServer(flags.arg.port)
app.static("/common", "app", internal=True)
app.redirect("/", "/meterman/")

# Main page.
app.page("/meterman",
"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name=viewport content="width=device-width, initial-scale=1">
  <title>meterman</title>
  <link rel="icon" href="/common/image/appicon.ico" type="image/x-icon" />
  <script type="module" src="/meterman/meterman.js"></script>
</head>
<body style="display: none">
  <meter-app id="app">
  </my-app>
</body>
</html>
""")

app.file("/meterman/meterman.js", "meterman.js", "text/javascript")

# Global state.
next_seq = 1
state = {
  "seq": 0,
  "software": "/meterman/download/metermon",
  "gateways": {},
  "history": flags.arg.history,
}

gateways = state["gateways"]
history = {}
lora = lorawan.LoRaServer()
state_update = threading.Event()

def state_updated():
  global next_seq
  state["seq"] = next_seq
  next_seq += 1
  state_update.set()
  state_update.clear()

@app.route("/meterman/state", method="GET")
def state_request(request):
  seq = int(request.param("seq"))

  # Wait for state update if client already has the current version.
  if seq == state["seq"]: state_update.wait(30)

  # Return "Not modified" if no changes
  if seq == state["seq"]: return 304

  # Return new state.
  return state

def get_gateway(gwid):
  gw = gateways.get(gwid)
  if gw is None:
    gw = {"gw": gwid, "meters":{}}
    gateways[gwid] = gw
  return gw

# Subscribe to meter messages on MQTT connect
def on_mqtt_connect(client, userdata, flags, reason_code, properties):
  # Subscribe to messages from meter gateways.
  client.subscribe("meter/data/#")

def discard_reading(reading):
 if reading is None: return False
 if type(reading) is not list: return False
 if len(reading) == 0: return False
 return reading[0].get("vif") == 127 and reading[0].get("value") != 0

# Handle meter messages and update global state.
def on_mqtt_message(client, userdata, msg):
  #log.info("message", msg.topic, msg.payload)
  try:
    message = json.loads(msg.payload)
  except Exception as e:
    log.info("invalid JSON message:", msg.payload)
    return

  log.info("message:", message)

  op = message.get("op")
  if op is None:
    log.info("invalid message: missing op")
    return

  gwid = message.get("gw")
  if gwid is None:
    log.info("invalid message: missing gateway id")
    return

  if op == "startup":
    log.info("startup", gwid)
    gw = get_gateway(gwid)
    gw["lastseen"] = message["ts"]
    gw["upsince"] = message["ts"]
    gw.update(message)
    state_updated()
  elif op == "inventory":
    log.info("inventory", gwid)
    gw = get_gateway(gwid)
    gw["lastseen"] = message["ts"]
    meters = gw["meters"]
    for m in message["meters"]:
      meterid = m["meterid"]
      meter = meters.get(meterid)
      if meter is None:
        meter = {}
        meters[meterid] = meter
      meter.update(m)
    state_updated()
  elif op == "lora":
    gw = get_gateway(gwid)
    gw["lastseen"] = message["ts"]
    ret = lora.onreceive(message)
    if ret != None:
      reply = ret[0]
      reading = ret[1]
      if reply:
        log.info("reply", reply)
        send_command(gw, reply)

  elif op == "reading":
    log.info("reading", gwid)
    gw = get_gateway(gwid)
    gw["lastseen"] = message["ts"]
    meters = gw["meters"]
    meterid = message.get("meterid")
    if meterid is None:
      log.info("missing meter id in reading")
      return

    meter = meters.get(meterid)
    if meter is None:
      meter = {}
      meters[meterid] = meter

    if message.get("encrypted"):
      key = aeskeys.get(meterid)
      if key:
        log.info("Send key to meter", meterid)
        send_command(gw, {"op": "key", "meterid": meterid, "key": key})

    reading = message.get("reading")

    if not discard_reading(reading):
      meter["encrypted"] = False
      meter.update(message)

    if flags.arg.history:
      if meterid not in history: history[meterid] = []
      history[meterid].append(str(msg.payload.decode()))

    state_updated()
  elif op == "console":
    gw = get_gateway(gwid)
    console = message["console"]
    gw["console"] = console
    state_updated()
  else:
    log.info("unknown message type:", op, "from", gwid)

# Start MQTT client.
mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqttc.on_connect = on_mqtt_connect
mqttc.on_message = on_mqtt_message
mqttc.connect(flags.arg.mqtt, 1883, 60)

def send_command(gw, msg):
  control = gw.get("control")
  if control is None: control = "meter/control/" + gw["gw"]
  mqttc.publish(control, json.dumps(msg))

@app.route("/meterman/reset", method="POST")
def reset_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404
  send_command(gw, {"op": "reset"})

@app.route("/meterman/timesync", method="POST")
def reset_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404
  ts = int(time.time())
  send_command(gw, {"op": "timesync", "ts": ts})

@app.route("/meterman/upgrade", method="POST")
def upgrade_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404

  f = open(flags.arg.appdir + "/metermon", "rb")
  data = f.read();
  f.close()

  msg = {"op": "upgrade", "binary": data.hex()}
  send_command(gw, msg)

@app.route("/meterman/forget", method="POST")
def forget_request(request):
  gwid = request.param("gw")
  if gwid in gateways:
    del gateways[gwid]
    state_updated()

@app.route("/meterman/command", method="POST")
def command_request(request):
  gwid = request.param("gw")
  command = request.body.decode()
  gw = gateways.get(gwid)
  if gw is None: return 404
  msg = {"op": "command", "command": command}
  send_command(gw, msg)

@app.route("/meterman/config", method="POST")
def config_request(request):
  gwid = request.param("gw")
  config = request.body.decode()
  gw = gateways.get(gwid)
  if gw is None: return 404
  log.info("config:", config)

  msg = {"op": "config", "config": config}
  send_command(gw, msg)

@app.route("/meterman/rescan", method="POST")
def rescan_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404
  send_command(gw, {"op": "rescan"})

@app.route("/meterman/log", method="POST")
def log_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404
  send_command(gw, {"op": "log"})

@app.route("/meterman/readings")
def readings_request(request):
  meterid = int(request.param("meterid"))
  readings = history.get(meterid)
  if readings is None: return 404
  return {"meterid":  meterid, "readings": readings}

@app.route("/meterman/download")
def down_request(request):
  app = flags.arg.appdir + "/metermon"
  return sling.net.HTTPFile(app, "application/octet-stream")

# Run app until shutdown.
log.info("running")
app.start()
mqttc.loop_forever()
