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

# sudo pip install pycryptodome

# lora {'op': 'lora', 'gw': '1357', 'bus': 'LoRa', 'device': 'lora0', 'ts': 1727183838, 'payload': '00000000d92dd5b370ed0000d92dd5b37039b1d194614b'}

import json
import time
import os.path

from Crypto.Hash import CMAC
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad

# LoRaWAN frame types.
LW_JOIN_REQUEST      = 0
LW_JOIN_ACCEPT       = 1
LW_DATA_UPLINK       = 2   # from end device to network
LW_DATA_DOWNLINK     = 3   # from network to to end device
LW_DATA_UPLINK_ACK   = 4
LW_DATA_DOWNLINK_ACK = 5

lora_keys_file = "local/lora-keys.txt"
lora_sessions_file = "local/lora-sessions.txt"

def reverse(b):
  return bytes(reversed(b))

def aes128_encrypt(key, data):
  ctx = AES.new(key, AES.MODE_ECB)
  return ctx.encrypt(pad(data, AES.block_size))

def aes128_decrypt(key, data):
  ctx = AES.new(key, AES.MODE_ECB)
  return ctx.decrypt(data)

def aes128_cmac(key, data):
  ctx = CMAC.new(key, ciphermod=AES)
  ctx.update(data)
  return ctx.digest()

def hexstr(eui):
  return eui.hex().upper()

def euistr(eui):
  return hexstr(reverse(eui))

class LoRaDevice:
  def __init__(self, config):
    self.deveui = reverse(bytes.fromhex(config["deveui"]))
    self.appeui = reverse(bytes.fromhex(config["appeui"]))
    self.appkey = bytes.fromhex(config["appkey"])
    self.netid = bytes.fromhex(config["netid"])
    self.devaddr = bytes.fromhex(config["devaddr"])
    self.join_eui = None
    self.dev_nounce = None
    self.join_nounce = None
    self.nwkskey = None
    self.appskey = None

  def add_session(self, session):
    self.dev_nounce = bytes.fromhex(session["devnounce"])
    self.join_nounce = bytes.fromhex(session["joinnounce"])
    self.nwkskey = bytes.fromhex(session["nwkskey"])
    self.appskey = bytes.fromhex(session["appskey"])

  def generate_session_keys(self, dev_nounce):
    # Generate random nounce.
    self.dev_nounce = dev_nounce
    self.join_nounce = get_random_bytes(3)

    # Compute network and app session keys.
    nounces = self.join_nounce + self.netid + self.dev_nounce
    self.nwkskey = aes128_encrypt(self.appkey, b'\0' + nounces)
    self.appskey = aes128_encrypt(self.appkey, b'\1' + nounces)

    # Append keys to session file.
    session = {
      "deveui": hexstr(self.deveui),
      "devnounce": hexstr(self.dev_nounce),
      "joinnounce": hexstr(self.join_nounce),
      "nwkskey": hexstr(self.nwkskey),
      "appskey": hexstr(self.appskey),
    }
    with open(lora_sessions_file, "a") as f:
      f.write(json.dumps(session) + "\n")

    print("session", session)

class LoRaServer:
  def __init__(self):
    self.loradevs = {}

    # Read LoRa keys and sessions.
    with open(lora_keys_file) as f:
      for line in f.readlines():
        line = line.strip()
        if len(line) == 0 or line[0] == '#': continue
        config = json.loads(line)
        dev = LoRaDevice(config)
        self.loradevs[dev.deveui] = dev

    if os.path.exists(lora_sessions_file):
      with open(lora_sessions_file) as f:
        for line in f.readlines():
          line = line.strip()
          if len(line) == 0 or line[0] == '#': continue
          session = json.loads(line)
          device = self.loradevs.get(bytes.fromhex(session["deveui"]))
          if device is None:
            print("Unknown LoRa session:", session)
          else:
            device.add_session(session)

  def join(self, gw, dev, payload):
    # Get JoinEUI, DevEUI, and DevNonce.
    if len(payload) != 1 + 8 + 8 + 2 + 4:
      print("LoRaWAN join request too short")
      return

    join_eui = payload[1:9]
    dev_eui = payload[9:17]
    dev_nounce = payload[17:19]
    mic = payload[19:23]

    print("LoRaWAN join request server %s device %s nounce %s mic %s" %
          (euistr(join_eui), euistr(dev_eui), hexstr(dev_nounce), hexstr(mic)))

    # Look up device configuration.
    device = self.loradevs.get(dev_eui)
    if device is None:
      print("Unknown LoRa device join", hexstr(dev_eui))
      return

    # Verify MIC.
    digest = aes128_cmac(device.appkey, payload[0:19])
    if digest[0:4] != mic:
      print("LoRaWAN MIC failed")
      return

    # Compute network and server session keys.
    device.generate_session_keys(dev_nounce)
    print("nwkskey:", hexstr(device.nwkskey))
    print("appskey:", hexstr(device.appskey))

    # Generate Join-Accept payload.
    # JoinNonce(3) NetID(3) DevAddr(4) DLSettings(1) RXDelay(1) CFList(opt)
    dl_settings = 0
    rx_delay = 0
    accept = device.join_nounce + device.netid + device.devaddr + \
             bytes([dl_settings, rx_delay])

    # Compute MIC for Join-Accept accept frame.
    mhdr = b'\x20'
    cmac = aes128_cmac(device.appkey, mhdr + accept)

    # Build encrypted reply packet.
    # Note: An AES decrypt operation in ECB mode encrypts the Join-Accept
    # frame so that the end-device can use an AES encrypt operation to
    # decrypt the frame. This way, an end-device has to implement only AES
    # encrypt but not AES decrypt.
    packet = mhdr + aes128_decrypt(device.appkey, pad(accept + cmac[0:4], 16))

    print("JOIN accept:", hexstr(packet))
    reply = {
     "op": "lora",
     "gw": gw,
     "device": dev,
     "payload": hexstr(packet),
    }
    reading = None

    # Test: JOIN_ACCEPT_DELAY1 (5s)
    time.sleep(1)

    return reply, reading

  def data(self, payload, uplink, ack):
    print("LoRa Data", uplink, ack, payload)

  def onreceive(self, msg):
    # Parse FHDR
    print("lora", msg)
    payload = bytes.fromhex(msg["payload"])
    fhdr = payload[0]
    ft = fhdr >> 5
    version = fhdr & 3
    print("lora frame", ft, "version", version)
    if version != 0:
      print("Unknown LoRa protocol version", version)
      return

    if ft == LW_JOIN_REQUEST:
      return self.join(msg["gw"], msg["device"], payload)
    elif ft == LW_JOIN_ACCEPT:
      print("LoRA JOIN accept ignored")
    elif ft == LW_DATA_UPLINK:
      return self.data(payload, True, False)
    elif ft == LW_DATA_DOWNLINK:
      return self.data(payload, False, False)
    elif ft == LW_DATA_UPLINK_ACK:
      return self.data(payload, True, True)
    elif ft == LW_DATA_DOWNLINK_ACK:
      return self.data(payload, False, True)
    else:
      print("Unknown LoRa frame type", ft)

#lora = LoRaServer()
#reply, reading = lora.onreceive({'op': 'lora', 'gw': '1357', 'bus': 'LoRa', 'device': 'lora0', 'ts': 1727183838, 'payload': '00000000d92dd5b370ed0000d92dd5b37039b1d194614b'})
#print(reply)

#reply, reading = onreceive({'op': 'lora', 'gw': '1357', 'bus': 'LoRa', 'device': 'lora0', 'ts': 1727183838, 'payload': '40F17DBE4900020001954378762B11FF0D'})

