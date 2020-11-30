import sys
import time

from RPi import GPIO

pins = [5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]

# Means use the pins as they are on the cobbler
# GPIO.BOARD means in order numbering
def setup():
    GPIO.setmode(GPIO.BCM)
    for pin in pins:
        GPIO.setup(pin, GPIO.OUT)

def main():
    while True:
        for idx, p in enumerate(pins):
            GPIO.output(p, GPIO.HIGH)
            print "Current pin", idx
            time.sleep(1)
            GPIO.output(p, GPIO.LOW)


if __name__ == "__main__":
    setup()
    main()
