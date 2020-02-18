#!/bin/bash
echo '# Running apt-get update ...'
apt-get update
echo '# Installing imagemagick ...'
apt-get install -y imagemagick
echo '# Installing blender ...'
apt-get install -y blender
echo '# Installing python-pip ...'
apt-get install -y python-pip
echo '# Installing azure-batch ...'
pip install azure-batch==4.1.3
echo '# Installing packages-microsoft-prod.deb ...'
wget -q https://packages.microsoft.com/config/ubuntu/16.04/packages-microsoft-prod.deb
sudo dpkg -i packages-microsoft-prod.deb
echo '# Installing apt-transport-https ...'
sudo apt-get -y install apt-transport-https
./install.sh
echo "## DONE ##"
exit $?

