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

# Parse command line flags.
flags.parse()

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
}

gateways = state["gateways"]

state_upate = threading.Event()

def state_updated():
  global next_seq
  state["seq"] = next_seq
  next_seq += 1
  state_upate.set()
  state_upate.clear()
  #print(json.dumps(state, indent=2))

@app.route("/meterman/state", method="GET")
def state_request(request):
  seq = int(request.param("seq"))

  # Wait for state update if client already has the current version.
  if seq == state["seq"]: state_upate.wait(30)

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

# Handle meter messages and update global state.
def on_mqtt_message(client, userdata, msg):
  #print("message", msg.topic, msg.payload)
  try:
    message = json.loads(msg.payload)
  except Exception as e:
    print("invalid JSON message:", msg.payload)
    return
  print("message:", message)

  op = message.get("op")
  if op is None:
    print("invalid message: missing op")
    return

  gwid = message.get("gw")
  if gwid is None:
    print("invalid message: missing gateway id")
    return

  if op == "startup":
    print("startup", gwid)
    gw = get_gateway(gwid)
    gw["lastseen"] = message["ts"]
    gw.update(message)
    state_updated()
  elif op == "inventory":
    print("inventory", gwid)
    gw = get_gateway(gwid)
    gw["lastseen"] = message["ts"]
    meters = gw["meters"]
    for m in message["meters"]:
      meterid = m["meterid"]
      meter = meters.get(meterid)
      if meter is None:
        meter = {"readings": []}
        meters[meterid] = meter
      meter.update(m)
    state_updated()
  elif op == "reading":
    print("reading", gwid)
    gw = get_gateway(gwid)
    gw["lastseen"] = message["ts"]
    meters = gw["meters"]
    meterid = message.get("meterid")
    if meterid is None:
      print("missing meter id in reading")
      return
    meter = meters.get(meterid)
    if meter is None:
      meter = {"readings": []}
      meters[meterid] = meter
    reading = message.get("reading")
    if reading is None or reading[0]["vif"] != 127:
      meter.update(message)
    if flags.arg.history: meter["readings"].append(message)
    state_updated()
  elif op == "console":
    gw = get_gateway(gwid)
    console = message["console"]
    gw["console"] = console
    state_updated()
  else:
    print("unknown message type:", op, "from", gwid)

# Start MQTT client.
mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqttc.on_connect = on_mqtt_connect
mqttc.on_message = on_mqtt_message
mqttc.connect(flags.arg.mqtt, 1883, 60)

@app.route("/meterman/reset", method="POST")
def reset_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404
  mqttc.publish(gw["control"], json.dumps({"op": "reset"}))

@app.route("/meterman/timesync", method="POST")
def reset_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404
  ts = int(time.time())
  mqttc.publish(gw["control"], json.dumps({"op": "timesync", "ts": ts}))

@app.route("/meterman/upgrade", method="POST")
def upgrade_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404

  f = open(flags.arg.appdir + "/metermon", "rb")
  data = f.read();
  f.close()

  print("upgrade", gwid, len(data), type(data))
  msg = {"op": "upgrade", "binary": data.hex()}
  mqttc.publish(gw["control"], json.dumps(msg))

@app.route("/meterman/forget", method="POST")
def forget_request(request):
  gwid = request.param("gw")
  del gateways[gwid]
  state_updated()

@app.route("/meterman/command", method="POST")
def command_request(request):
  gwid = request.param("gw")
  command = request.body.decode()
  gw = gateways.get(gwid)
  if gw is None: return 404
  msg = {"op": "command", "command": command}
  mqttc.publish(gw["control"], json.dumps(msg))

@app.route("/meterman/config", method="POST")
def config_request(request):
  gwid = request.param("gw")
  config = request.body.decode()
  gw = gateways.get(gwid)
  if gw is None: return 404
  print("config:", config)

  msg = {"op": "config", "config": config}
  mqttc.publish(gw["control"], json.dumps(msg))

@app.route("/meterman/rescan", method="POST")
def rescan_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404
  mqttc.publish(gw["control"], json.dumps({"op": "rescan"}))

@app.route("/meterman/log", method="POST")
def log_request(request):
  gwid = request.param("gw")
  gw = gateways.get(gwid)
  if gw is None: return 404
  mqttc.publish(gw["control"], json.dumps({"op": "log"}))

@app.route("/meterman/download")
def down_request(request):
  app = flags.arg.appdir + "/metermon"
  return sling.net.HTTPFile(app, "application/octet-stream")

# Run app until shutdown.
log.info("running")
app.start()
mqttc.loop_forever()

