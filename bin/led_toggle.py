import sys

from RPi import GPIO

pins = [5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]

# Means use the pins as they are on the cobbler
# GPIO.BOARD means in order numbering
def setup():
    GPIO.setmode(GPIO.BCM)
    for pin in pins:
        GPIO.setup(pin, GPIO.OUT)

def main(mode, pin):
    toggle = True
    if mode in ["on", "off"]:
        state = GPIO.LOW
        if mode == "on":
            state = GPIO.HIGH
        for p in pins:
            if pin >= 0 and p != pin:
                continue
            GPIO.output(p, state)
    else:
        for p in pins:
            current_state = GPIO.input(p)
            new_state = not current_state
            new_state = new_state and GPIO.HIGH or GPIO.LOW
            GPIO.output(p, new_state)


if __name__ == "__main__":
    setup()
    mode = "toggle"
    pin = -1
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode not in ["on", "off"]:
            print "Unrecognized mode"
            sys.exit(1)

    if len(sys.argv) > 2:
        pin = int(sys.argv[2])
        if pin not in pins:
            print "Unrecognized pin"
            sys.exit(1)

    main(mode, pin)
