#!/usr/bin/env python3
import itertools
import logging
import os
import re
import shlex
import subprocess
import sys
from collections import namedtuple
from pathlib import Path
from shutil import copyfile

import yaml

_LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

maindir = sys.argv[1]


def is_root() -> bool:
    return True if os.geteuid() == 0 else False


def flatten(data) -> list:
    return list(itertools.chain.from_iterable(data))


def run_command(cmd: list[str]) -> bool:
    try:
        _LOGGER.info("Running command %s", cmd)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for line in p.stdout:
            pass
        out, err = p.communicate()
        # subprocess.run(
        #     cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True
        # )
        if p.returncode in (1, 255):
            return False
    except subprocess.CalledProcessError:
        return False
    return True


Response = namedtuple("Response", "returncode value")


class Whiptail:
    def __init__(
        self,
        title: str = "",
        backtitle: str = "",
        height: int = 20,
        width: int = 60,
        auto_exit: bool = True,
    ):
        self.title = title
        self.backtitle = backtitle
        self.height = height
        self.width = width
        self.auto_exit = auto_exit

    def run(
        self, control: str, msg: str, extra: tuple = (), exit_on: tuple = (1, 255)
    ) -> Response:
        cmd = [
            "whiptail",
            "--title",
            self.title,
            "--backtitle",
            self.backtitle,
            "--" + control,
            msg,
            str(self.height),
            str(self.width),
        ]
        cmd += list(extra)
        p = subprocess.Popen(cmd, stderr=subprocess.PIPE)
        out, err = p.communicate()
        if self.auto_exit and p.returncode in exit_on:
            sys.exit(p.returncode)
        return Response(p.returncode, str(err, "utf-8", "ignore"))

    def prompt(self, msg: str, default: str = "", password: bool = False) -> str:
        control = "passwordbox" if password else "inputbox"
        return self.run(control, msg, [default]).value

    def confirm(self, msg: str, default: str = "yes") -> bool:
        defaultno = "--defaultno" if default == "no" else ""
        return self.run("yesno", msg, [defaultno], [255]).returncode == 0

    def alert(self, msg: str) -> None:
        self.run("msgbox", msg)

    def view_file(self, path: str) -> None:
        self.run("textbox", path, ["--scrolltext"])

    def calc_height(self, msg: str) -> list[str]:
        height_offset = 8 if msg else 7
        return [str(self.height - height_offset)]

    def menu(self, msg: str = "", items: tuple = (), prefix: str = " - ") -> str:
        if isinstance(items[0], str):
            items = [(i, "") for i in items]
        else:
            items = [(k, prefix + v) for k, v in items]
        extra = self.calc_height(msg) + flatten(items)
        return self.run("menu", msg, extra).value

    def showlist(self, control: str, msg: str, items, prefix: str) -> list[str]:
        if isinstance(items[0], str):
            items = [(tag, "", "OFF") for tag in items]
        else:
            items = [(tag, prefix + value, state) for tag, value, state in items]
        extra = self.calc_height(msg) + flatten(items)
        return shlex.split(self.run(control, msg, extra).value)

    def show_tag_only_list(
        self, control: str, msg: str, items, prefix: str
    ) -> list[str]:
        if isinstance(items[0], str):
            items = [(tag, "", "OFF") for tag in items]
        else:
            items = [(tag, "", state) for tag, value, state in items]
        extra = self.calc_height(msg) + flatten(items)
        return shlex.split(self.run(control, msg, extra).value)

    def radiolist(self, msg: str = "", items: tuple = (), prefix: str = " - ") -> str:
        ret_list = self.showlist("radiolist", msg, items, prefix)
        return ret_list[0] if len(ret_list) > 0 else []

    def node_radiolist(self, msg: str = "", items: tuple = (), prefix: str = "") -> str:
        return self.show_tag_only_list("radiolist", msg, items, prefix)[0]

    def checklist(
        self, msg: str = "", items: tuple = (), prefix: str = " - "
    ) -> list[str]:
        return self.showlist("checklist", msg, items, prefix)


def read_os_release() -> dict[str, str]:
    return {
        k.lower(): v.strip("'\"")
        for k, v in (
            line.strip().split("=", 1)
            for line in Path.open("/etc/os-release").read().strip().split("\n")
        )
    }


def check_os() -> bool:
    if Path("/etc/debian_version").is_file():
        os_data = read_os_release()
        if os_data["id"] == "debian" and int(os_data["version_id"]) == 10:
            return True
        _LOGGER.error("Wrong OS type.")
        return False


def check_arch() -> bool:
    uname = os.uname()
    if uname.machine == "armv7l":
        return True
    _LOGGER.error(
        "This architecture is not supported. Is it Beaglebone? %s", uname.machine
    )
    return False


class BoneIODumper(yaml.Dumper):  # pylint: disable=too-many-ancestors
    def represent_stringify(self, value):
        return self.represent_scalar(tag="tag:yaml.org,2002:str", value=str(value))

    def represent_none(self, v):
        return self.represent_scalar(tag="tag:yaml.org,2002:null", value="")


BoneIODumper.add_representer(str, BoneIODumper.represent_stringify)

BoneIODumper.add_representer(type(None), BoneIODumper.represent_none)

ON = "ON"
OFF = "OFF"
if __name__ == "__main__":
    if is_root():
        _LOGGER.error("Can't run this script as root!")
        sys.exit(1)
    if not check_os() or not check_arch():
        _LOGGER.error("Wrong operating system or CPU architecture!")
        sys.exit(1)
    py_version = sys.version_info
    if py_version[:2] < (3, 7):
        _LOGGER.error("Wrong Python version")
        exit(1)
    whiptail = Whiptail(
        title="boneIO", backtitle="Installation script", height=20, width=80
    )
    _LOGGER.info("Installing BoneIO package")
    _command = run_command(
        cmd=shlex.split(f"{maindir}/venv/bin/pip3 install --upgrade boneio")
    )
    if not _command:
        _LOGGER.error("BoneIO installed failed.")
        sys.exit(1)
    _configure = whiptail.confirm(
        msg="Would you like to give some basic mqtt credentials so we can configure boneio for you?"
    )
    if _configure:
        _boneio_name = whiptail.prompt("Name for this BoneIO", default="myboneio")
        _mqtt_hostname = whiptail.prompt("Type mqtt hostname", default="localhost")
        _mqtt_username = whiptail.prompt("Type mqtt username", default="mqtt")
        _mqtt_password = whiptail.prompt("Type mqtt password", password=True)
        _ha_discovery = whiptail.confirm(msg="Enable HA discovery", default="yes")
        _oled_enabled = whiptail.confirm(
            msg="Do you want OLED screen ON", default="yes"
        )
        _enabled_inputs = whiptail.checklist(
            "Inputs",
            items=[
                (
                    "Event entities",
                    "Event entities. 1-47 will be configures as event entities.",
                    ON,
                ),
                (
                    "Binary sensors",
                    "Binary sensors. Last 3 inputs will be configured as binary sensors.",
                    ON,
                ),
            ],
        )
        _enabled_outputs = whiptail.radiolist(
            "Outputs, choose which output you want to enable.",
            items=[
                ("RB32", "Relay board 32x5A", OFF),
                ("RB3210", "Relay board 32x10A", OFF),
                ("RB24", "Relay board 24x16A", OFF),
            ],
        )
        _enabled_sensors = whiptail.checklist(
            "Sensors, choose which sensors you have onboard.",
            items=[
                (
                    "LM75_RB24",
                    "LM75 temp sensor on Relay board 24x16A",
                    OFF,
                ),
                (
                    "LM75_RB32",
                    "LM75 temp sensor on Relay board 32x5A or 32x10A",
                    OFF,
                ),
                (
                    "MCP9808_RB32",
                    "MCP9808 temp sensor on Relay board 32x5A",
                    OFF,
                ),
                (
                    "ADC",
                    "ADC input sensors, don't use if nothing is connected to those inputs",
                    OFF,
                ),
            ],
        )
        mqtt_part = {
            "host": _mqtt_hostname,
            "topic_prefix": _boneio_name,
            "ha_discovery": {"enabled": _ha_discovery},
            "username": _mqtt_username,
            "password": _mqtt_password,
        }
        output = {"mqtt": mqtt_part}
        exampled_dir = (
            f"{maindir}/venv/lib/python{py_version.major}.{py_version.minor}"
            "/site-packages/boneio/example_config/"
        )
        Path(maindir).mkdir(parents=True, exist_ok=True)
        if _oled_enabled:
            output["oled"] = {"enabled": True}
        if "RB24" in _enabled_outputs:
            copyfile(f"{exampled_dir}output24x16A.yaml", f"{maindir}/output24x16A.yaml")
            output["mcp23017"] = [
                {"id": "mcp1", "address": "0x20"},
                {"id": "mcp2", "address": "0x21"},
            ]
            output["output"] = "!include output24x16A.yaml"
        elif "RB32" in _enabled_outputs:
            copyfile(f"{exampled_dir}output32x5A.yaml", f"{maindir}/output32x5A.yaml")
            # Ensure mcp23017 is a list before appending
            if "mcp23017" in output and isinstance(output["mcp23017"], list):
                output["mcp23017"].append({"id": "mcp1", "address": "0x22"})
                output["mcp23017"].append({"id": "mcp1", "address": "0x23"})
            else:
                output["mcp23017"] = [
                    {"id": "mcp1", "address": "0x22"},
                    {"id": "mcp2", "address": "0x23"},
                ]
            output["output"] = "!include output32x5A.yaml"
        if "LM75_RB32" in _enabled_sensors or "LM75_RB24" in _enabled_sensors:
            output["lm75"] = [{"id": "temp", "address": "0x72"}]
        if "Event entities" and "Binary sensors" in _enabled_inputs:
            copyfile(f"{exampled_dir}event.yaml", f"{maindir}/event.yaml")
            copyfile(
                f"{exampled_dir}binary_sensor.yaml", f"{maindir}/binary_sensor.yaml"
            )
            output["event"] = "!include event.yaml"
            output["binary_sensor"] = "!include binary_sensor.yaml"
        elif "Event entities" in _enabled_inputs:
            copyfile(f"{exampled_dir}event_all.yaml", f"{maindir}/event.yaml")
            output["event"] = "!include event.yaml"
        elif "Binary sensors" in _enabled_inputs:
            copyfile(
                f"{exampled_dir}binary_sensor_all.yaml", f"{maindir}/binary_sensor.yaml"
            )
            output["binary_sensor"] = "!include binary_sensor.yaml"

        if "ADC" in _enabled_sensors:
            copyfile(f"{exampled_dir}adc.yaml", f"{maindir}/adc.yaml")
            output["adc"] = "!include adc.yaml"

        with Path(f"{maindir}/config.yaml").open("w+") as file:
            result = re.sub(
                r"(.*): (')(.+)(')",
                "\\1: \\3",
                yaml.dump(
                    output,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                    Dumper=BoneIODumper,
                ),
                0,
            )
            file.write(result)
    _configure = whiptail.confirm(
        msg="Would you like to create startup script for you?"
    )
    if _configure:
        with Path(f"{maindir}/boneio.service").open("w+") as file:
            file.write(
                f"""[Unit]
Description=boneIO
After=multi-user.target

[Service]
Type=simple
ExecStart={maindir}/venv/bin/boneio run -c {maindir}/config.yaml

[Install]
WantedBy=multi-user.target
"""
            )
        _configure = whiptail.confirm(
            msg="Start BoneIO at system startup automatically?"
        )
        if _configure:
            run_command(
                cmd=shlex.split(
                    f"sudo cp {maindir}/boneio.service /lib/systemd/system/boneio.service"
                )
            )
            run_command(cmd=shlex.split("sudo systemctl daemon-reload"))
            run_command(cmd=shlex.split("sudo systemctl enable --now boneio"))
    whiptail.alert(
        f"Your config is in {maindir}/config.yaml. Change it according to your needs.\n Read more at https://boneio.eu"
    )
    sys.exit(0)
