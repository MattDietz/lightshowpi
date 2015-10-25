#!/usr/bin/env python
#
# Licensed under the BSD license.  See full license in LICENSE file.
# http://www.lightshowpi.com/
#
# Author: Ryan Jennings
# Author: Chris Usey
# Author: Todd Giles (todd@lightshowpi.com)
# Author: Tom Enos (tomslick.ca@gmail.com)

"""Control the raspberry pi hardware.

The hardware controller handles all interaction with the raspberry pi
hardware to turn the lights on and off.

Third party dependencies:

wiringpi2: python wrapper around wiring pi
    https://github.com/WiringPi/WiringPi2-Python
"""

import argparse
import atexit
import logging
import math
import time
import subprocess
import Platform
import configuration_manager as cm


is_a_raspberryPI = Platform.platform_detect() == 1


if is_a_raspberryPI:
    import wiringpi2 as wiringpi
else:
    # if this is not a RPi you can't run wiringpi so lets load
    # something in its place
    import wiring_pi_stub as wiringpi
    logging.debug("Not running on a raspberryPI")


# Get Configurations - TODO(todd): Move more of this into configuration manager
_CONFIG = cm.CONFIG
_LIGHTSHOW_CONFIG = cm.lightshow()
_HARDWARE_CONFIG = cm.hardware()
_GPIO_PINS = [int(gpio_pin) for gpio_pin in
              _CONFIG.get('hardware', 'gpio_pins').split(',')]
_PWM_MAX = int(_CONFIG.get('hardware', 'pwm_range'))
_ACTIVE_LOW_MODE = _CONFIG.getboolean('hardware', 'active_low_mode')
_ALWAYS_ON_CHANNELS = [int(channel) for channel in
                       _LIGHTSHOW_CONFIG['always_on_channels'].split(',')]
_ALWAYS_OFF_CHANNELS = [int(channel) for channel in
                        _LIGHTSHOW_CONFIG['always_off_channels'].split(',')]
_INVERTED_CHANNELS = [int(channel) for channel in
                      _LIGHTSHOW_CONFIG['invert_channels'].split(',')]
_EXPORT_PINS = _CONFIG.getboolean('hardware', 'export_pins')
_GPIO_UTILITY_PATH = _CONFIG.get('hardware', 'gpio_utility_path')

I2C_DEVICES = ["mcp23017", "mcp23016", "mcp23008", "pcf8574"]
SPI_DEVICES = ["mcp23s08", "mcp23s17"]

PIN_MODES = _CONFIG.get('hardware', 'pin_modes').split(',')

# Initialize GPIO
_GPIOASINPUT = 0
_GPIOASOUTPUT = 1

GPIOLEN = len(_GPIO_PINS)


# If only a single pin mode is specified, assume all pins should be in that
# mode
if len(PIN_MODES) == 1:
    PIN_MODES = [PIN_MODES[0]] * GPIOLEN


is_pin_pwm = list()
for mode in range(len(PIN_MODES)):
    if PIN_MODES[mode] == "pwm":
        is_pin_pwm.append(True)
    else:
        is_pin_pwm.append(False)

# Check ActiveLowMode Configuration Setting
if _ACTIVE_LOW_MODE:
    # Enabled
    _GPIOACTIVE = 0
    _PWM_ON = 0
    _GPIOINACTIVE = 1
    _PWM_OFF = _PWM_MAX
else:
    # Disabled
    _GPIOACTIVE = 1
    _PWM_ON = _PWM_MAX
    _GPIOINACTIVE = 0
    _PWM_OFF = 0


# Functions
def enable_device():
    """enable the specified device """
    try:
        devices = _HARDWARE_CONFIG['devices']
        for device, device_slaves in devices.keys():
            func_name = "%sSetup" % device
            if not hasattr(wiringpi, func_name):
                logging.error("Requested device %s is not supported, "
                              "please check your devices settings: "
                              % str(device))
                continue

            setup = getattr(wiringpi, func_name)

            for slave in device_slaves:
                params = slave
                base_args, extra_args = [params["pinBase"]], []

                if device in I2C_DEVICES:
                    extra_args = [params['i2cAddress'], 16]
                elif device in SPI_DEVICES:
                    extra_args = [params['spiPort'], params['devId'], 16]
                else:
                    if device == "sr595":
                        extra_args = [params['numPins'], params['dataPin'],
                                      params['clockPin'], params['latchPin']]

                base_args.extend(map(int, extra_args))
                setup(*args)

    except Exception as error:
        logging.exception("Error setting up devices, please check your "
                          "devices settings.")


def set_all_pins_as_outputs():
    """Set all the configured pins as outputs."""
    for pin in xrange(GPIOLEN):
        set_pin_as_output(pin)


def set_pin_as_output(pin):
    """Set the specified pin as an output.

    :param pin: index of pin in _GPIO_PINS
    :type pin: int
    """
    if _EXPORT_PINS and is_a_raspberryPI:
        # set pin as output for use in export mode
        subprocess.check_call([_GPIO_UTILITY_PATH, 'export',
                               str(_GPIO_PINS[pin]), 'out'])
    else:
        if is_pin_pwm[pin]:
            wiringpi.softPwmCreate(_GPIO_PINS[pin], 0, _PWM_MAX)
        else:
            wiringpi.pinMode(_GPIO_PINS[pin], _GPIOASOUTPUT)


def set_all_pins_as_inputs():
    """Set all the configured pins as inputs."""
    for pin in xrange(GPIOLEN):
        set_pin_as_input(pin)


def set_pin_as_input(pin):
    """Set the specified pin as an input.

    :param pin: index of pin in _GPIO_PINS
    :type pin: int
    """
    if _EXPORT_PINS and is_a_raspberryPI:
        # set pin as input for use in export mode
        subprocess.check_call([_GPIO_UTILITY_PATH, 'export',
                               str(_GPIO_PINS[pin]), 'in'])
    else:
        wiringpi.pinMode(_GPIO_PINS[pin], _GPIOASINPUT)


def turn_off_all_lights(use_always_onoff=False):
    """
    Turn off all the lights

    But leave on all lights designated to be always on if specified.

    :param use_always_onoff: boolean, should always on/off be used
    :type use_always_onoff: bool
    """
    for pin in xrange(GPIOLEN):
        turn_off_light(pin, use_always_onoff)


def turn_off_light(pin, use_overrides=False):
    """
    Turn off the specified light

    Taking into account various overrides if specified.

    :param pin: index of pin in _GPIO_PINS
    :type pin: int

    :param use_overrides: should overrides be used
    :type use_overrides: bool
    """
    if use_overrides:
        if is_pin_pwm[pin]:
            turn_on_light(pin, use_overrides, _PWM_OFF)
        else:
            if pin + 1 not in _ALWAYS_OFF_CHANNELS:
                if pin + 1 not in _INVERTED_CHANNELS:
                    wiringpi.digitalWrite(_GPIO_PINS[pin], _GPIOINACTIVE)
                else:
                    wiringpi.digitalWrite(_GPIO_PINS[pin], _GPIOACTIVE)
    else:
        if is_pin_pwm[pin]:
            wiringpi.softPwmWrite(_GPIO_PINS[pin], _PWM_OFF)
        else:
            wiringpi.digitalWrite(_GPIO_PINS[pin], _GPIOINACTIVE)


def turn_on_all_lights(use_always_onoff=False):
    """
    Turn on all the lights

    But leave off all lights designated to be always off if specified.

    :param use_always_onoff: should always on/off be used
    :type use_always_onoff: bool
    """
    for pin in xrange(GPIOLEN):
        turn_on_light(pin, use_always_onoff)


def turn_on_light(pin, use_overrides=False, brightness=1.0):
    """Turn on the specified light

    Taking into account various overrides if specified.

    :param pin: index of pin in _GPIO_PINS
    :type pin: int

    :param use_overrides: should overrides be used
    :type use_overrides: bool

    :param brightness: float, a float representing the brightness of the lights
    :type brightness: float
    """
    if is_pin_pwm[pin]:
        if math.isnan(brightness):
            brightness = 0.0
        if _ACTIVE_LOW_MODE:
            brightness = 1.0 - brightness
        if brightness < 0.0:
            brightness = 0.0
        if brightness > 1.0:
            brightness = 1.0
        if use_overrides:
            if pin + 1 in _ALWAYS_OFF_CHANNELS:
                brightness = 0
            elif pin + 1 in _ALWAYS_ON_CHANNELS:
                brightness = 1
            if pin + 1 in _INVERTED_CHANNELS:
                brightness = 1 - brightness
        wiringpi.softPwmWrite(_GPIO_PINS[pin], int(brightness * _PWM_MAX))
        return

    if use_overrides:
        if pin + 1 not in _ALWAYS_OFF_CHANNELS:
            if pin + 1 not in _INVERTED_CHANNELS:
                wiringpi.digitalWrite(_GPIO_PINS[pin], _GPIOACTIVE)
            else:
                wiringpi.digitalWrite(_GPIO_PINS[pin], _GPIOINACTIVE)
    else:
        wiringpi.digitalWrite(_GPIO_PINS[pin], _GPIOACTIVE)


def demo_fade(lights, flashes, sleep):
    print "Press <CTRL>-C to stop"
    while True:
        for light in lights:
            if is_pin_pwm[light]:
                for _ in xrange(flashes):
                    for brightness in xrange(0, _pwm_max):
                        # fade in
                        turn_on_light(light, false,
                                      float(brightness) / _pwm_max)
                        time.sleep(sleep / _pwm_max)
                    for brightness in xrange(_pwm_max - 1, -1, -1):
                        # fade out
                        turn_on_light(light, false,
                                      float(brightness) / _pwm_max)
                        time.sleep(sleep / _pwm_max)



def demo_flashes(lights, flashes, sleep):
    print "Press <CTRL>-C to stop"
    while True:
        for light in lights:
            print "channel %s " % light
            for _ in xrange(flashes):
                turn_on_light(light)
                time.sleep(sleep)
                turn_off_light(light)
                time.sleep(sleep)


def clean_up():
    """
    Clean up and end the lightshow

    Turn off all lights and set the pins as inputs
    """
    print "Cleaning up..."
    turn_off_all_lights()
    set_all_pins_as_inputs()
    if _EXPORT_PINS:
        subprocess.check_call([_GPIO_UTILITY_PATH, 'unexportall'])


def initialize():
    """Set pins as outputs and start all lights in the off state."""
    if _EXPORT_PINS:
        logging.info("Running as non root user, disabling pwm mode on "
                     "all pins")

        for pin in xrange(GPIOLEN):
            PIN_MODES[pin] = "onoff"
            is_pin_pwm[pin] = False
        wiringpi.wiringPiSetupSys()
    else:
        wiringpi.wiringPiSetup()
        enable_device()

    set_all_pins_as_outputs()
    turn_off_all_lights()


def main():
    """main"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', choices=["off", "on", "flash",
                                            "fade", "cleanup"],
                        help='turn off, on, flash, or cleanup')
    parser.add_argument('--light', default='-1',
                        help='the lights to act on (comma delimited list), '
                             '-1 for all lights')
    parser.add_argument('--sleep', default=0.5,
                        help='how long to sleep between flashing or fading '
                             'a light')
    parser.add_argument('--flashes', default=2,
                        help='the number of times to flash or fade each '
                             'light')
    args = parser.parse_args()
    state = args.state
    sleep = float(args.sleep)
    flashes = int(args.flashes)
    atexit.register(clean_up)

    if "-1" in args.light:
        lights = range(0, len(_GPIO_PINS))
    else:
        lights = [int(light) for light in args.light.split(',')]

    initialize()

    if state == "cleanup":
        clean_up()
    elif state == "off":
        turn_off_all_lights()
    elif state == "on":
        turn_on_all_lights()
    elif state == "fade":
        demo_fade(lights, flashes, sleep)
    elif state == "flash":
        demo_flashes(lights, flashes, sleep)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
