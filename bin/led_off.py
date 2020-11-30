import time

from RPi import GPIO

pins = [5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]

def turn_off():
    for pin in pins:
        GPIO.output(pin, GPIO.LOW)
    GPIO.cleanup()

# Means use the pins as they are on the cobbler
# GPIO.BOARD means in order numbering
def setup():
    GPIO.setmode(GPIO.BCM)
    for pin in pins:
        GPIO.setup(pin, GPIO.OUT)

def main():
    toggle = True
    for pin in pins:
        GPIO.output(pin, GPIO.LOW)


if __name__ == "__main__":
    setup()
    main()
