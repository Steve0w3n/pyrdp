#!/usr/bin/python3

#
# This file is part of the PyRDP project.
# Copyright (C) 2018, 2020 GoSecure Inc.
# Licensed under the GPLv3 or later.
#

import argparse
from pathlib import Path
import struct

from progressbar import progressbar
from scapy.all import *

from pyrdp.logging import LOGGER_NAMES, SessionLogger
from pyrdp.mitm import MITMConfig, RDPMITM
from pyrdp.mitm.MITMRecorder import MITMRecorder
from pyrdp.mitm.state import RDPMITMState
from pyrdp.recording import FileLayer


def bytesToIP(data: bytes):
    return ".".join(str(b) for b in data)


def parseExportedPdu(packet: packet.Raw):
    source = packet.load[12: 16]
    source = bytesToIP(source)

    destination = packet.load[20: 24]
    destination = bytesToIP(destination)

    data = packet.load[60:]
    return source, destination, data


class CustomMITMRecorder(MITMRecorder):
    currentTimeStamp: int = None

    def getCurrentTimeStamp(self) -> int:
        return self.currentTimeStamp

    def setTimeStamp(self, timeStamp: int):
        self.currentTimeStamp = timeStamp


class RDPReplayerConfig(MITMConfig):
    @property
    def replayDir(self) -> Path:
        return self.outDir

    @property
    def fileDir(self) -> Path:
        return self.outDir


class RDPReplayer(RDPMITM):
    def __init__(self, output_path: str):
        def sendBytesStub(_: bytes):
            pass

        output_path = Path(output_path)
        output_directory = output_path.absolute().parent

        logger = logging.getLogger(LOGGER_NAMES.MITM_CONNECTIONS)
        log = SessionLogger(logger, "replay")

        config = RDPReplayerConfig()
        config.outDir = output_directory
        # We'll set up the recorder ourselves
        config.recordReplays = False

        replay_transport = FileLayer(output_path)
        state = RDPMITMState()
        super().__init__(log, log, config, state, CustomMITMRecorder([replay_transport], state))

        self.client.tcp.sendBytes = sendBytesStub
        self.server.tcp.sendBytes = sendBytesStub
        self.state.useTLS = True

    def start(self):
        pass

    def recv(self, data: bytes, from_client: bool):
        if from_client:
            self.client.tcp.dataReceived(data)
        else:
            self.server.tcp.dataReceived(data)

    def setTimeStamp(self, timeStamp: float):
        self.recorder.setTimeStamp(int(timeStamp * 1000))

    def connectToServer(self):
        pass

    def startTLS(self):
        pass

    def sendPayload(self):
        pass


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("input", help="Path to PCAP file with exported PDUs. "
                                          "Using Wireshark: File -> Export PDUs to File "
                                          "then pick OSI Layer 7 and click Ok and "
                                          "save the result as a pcap file.")
    arg_parser.add_argument("client", help="Client IP address")
    arg_parser.add_argument("server", help="Server IP address (usually it's the MITM IP address)")
    arg_parser.add_argument("output", help="Output file that will be playable in pyrdp-player.py")
    arguments = arg_parser.parse_args(sys.argv[1 :])

    logging.basicConfig(level=logging.CRITICAL)
    logging.getLogger("scapy").setLevel(logging.ERROR)
    client_ip = arguments.client
    server_ip = arguments.server

    input_path = arguments.input
    output_path = arguments.output
    packets = rdpcap(input_path)

    replayer = RDPReplayer(output_path)

    for packet in progressbar(packets):
        # The packets start with a Wireshark exported PDU structure
        source, destination, data = parseExportedPdu(packet)

        if source not in [client_ip, server_ip] or destination not in [client_ip, server_ip]:
            continue

        try:
            replayer.setTimeStamp(float(packet.time))
            replayer.recv(data, source == client_ip)
        except NotImplementedError as e:
            raise e

    try:
        replayer.tcp.recordConnectionClose()
    except struct.error as e:
        print("Couldn't close the connection cleanly. "
              "Are you sure you got source and destination correct?")


if __name__ == "__main__":
    main()