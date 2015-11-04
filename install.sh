#!/bin/bash
#
# Licensed under the BSD license.  See full license in LICENSE file.
# http://www.lightshowpi.com/
#
# Syncronized_lights installer
#
# Author: Sean Millar sean.millar@gmail.com
#
# Install assumes this is a Rasberry Pi and python 2.7 is used.


#TODO(sean): Better Error Handling
#TODO(sean): Clean this up so it looks pretty
#TODO(mdietz): Only works on apt systems. No yum?
LOGFILE=install.log
PATH=$PATH
export PATH
exec > >(tee $LOGFILE)
INSTALL_DIR="$( cd "$(dirname "$0")" ; pwd -P )"
BUILD_DIR=${INSTALL_DIR}/build_dir

# This is not the way to do this
PYTHON_PATH=/usr/lib/python2.7
PYTHON_REQUIREMENTS_PATH=requirements.txt

    ENV_VARIABLE="SYNCHRONIZED_LIGHTS_HOME=${INSTALL_DIR}"
exists=`grep -r "$ENV_VARIABLE" /etc/profile*`

# Root check
function check_uid {
  if [ "$EUID" -ne 0 ]; then
    echo "This must be run as root. Please re-run as 'sudo $0'"
    exit 1
  fi
  return 0
}

function log_on_error {
  # basic error reporting
  if [ $2 -ne 0 ]; then
    echo "Houston we have a problem....."
    echo "$1 failed with exit code $2"
    exit 1
  fi
}

check_uid

# Defaults to install where install.sh is located
pushd .
if [ -f $BUILD_DIR ]; then
  rm -rf $BUILD_DIR
fi

mkdir -p $BUILD_DIR
cd $BUILD_DIR

# update first
apt-get update

# Doesn't hurt to try to install things even if some are already installed
apt-get install -y git python-setuptools python-pip python-dev build-essential mercurial
pip install python-setuptools --upgrade

# Install python packages from pypi
popd
pip install -r $PYTHON_REQUIREMENTS_PATH
log_on_error "Installing required python packages..." $?

# install python-alsaaudio
apt-get install -y python-alsaaudio
log_on_error "Installing python-alsaaudio" $?

# install audio encoders
apt-get install -y lame flac faad vorbis-tools
log_on_error "Installing audio-encoders" $?

# install audio encoder ffmpeg (wheezy) or libav-tools (Jessie or OSMC)
version=$(cat /etc/*-release | grep 'VERSION_ID' | awk -F \" '{print $2}')
declare -i version

if [ $version -le 7 ] ; then
  AUDIO_DEODER=ffmpeg
  apt-get install -y ffmpeg
else
  AUDIO_DECODER=libav-tools
  apt-get install -y libav-tools

  # create symlink to avconv so the decoder can still work
  echo "creating symlink to avconv"
  ln -s /usr/bin/avconv /usr/bin/ffmpeg
fi
log_on_error "Installing $AUDIO_DECODER" $?

# install mpg123
apt-get install -y mpg123
log_on_error "Installing mpg123" $?

# Setup environment variables

if [ -z "$exists" ]; then
  echo "# Lightshow Pi Home" > /etc/profile.d/lightshowpi.sh
  echo "$ENV_VARIABLE" >> /etc/profile.d/lightshowpi.sh
  echo "export SYNCHRONIZED_LIGHTS_HOME" >> /etc/profile.d/lightshowpi.sh
  echo "" >> /etc/profile.d/lightshowpi.sh
  echo "# Add Lightshow Pi bin directory to path" >> /etc/profile.d/lightshowpi.sh
  echo "PATH=\$PATH:${INSTALL_DIR}/bin" >> /etc/profile.d/lightshowpi.sh
  echo "export PATH" >> /etc/profile.d/lightshowpi.sh

  # Force set this environment variable in this shell (as above doesn't take until reboot)
  export $ENV_VARIABLE
fi

KEEP_EN="Defaults	env_keep="SYNCHRONIZED_LIGHTS_HOME""
exists=`grep "$KEEP_EN" /etc/sudoers`

if [ -z "$exists" ]; then
  echo "$KEEP_EN" >> /etc/sudoers
fi

# Explain to installer how they can test to see if we are working
echo
echo "You may need to reboot your Raspberry Pi before running lightshowPi (sudo reboot)."
echo "Run the following command to test your installation and hardware setup (press CTRL-C to stop the test):"
echo
echo "sudo python $INSTALL_DIR/py/hardware_controller.py --state=flash"
echo
