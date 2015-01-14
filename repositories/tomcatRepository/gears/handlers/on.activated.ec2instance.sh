#!/bin/bash

# Install chef if necessary
if [ ! "knife --version" ]; then
    curl -L https://www.chef.io/chef/install.sh | sudo bash
    cd /tmp
    mkdir chef
    git clone git://github.com/opscode/chef-repo.git /tmp/chef
    knife configure client ~/.chef -r /tmp/chef
    sudo mkdir /etc/chef-server
    sudo cp -f ~/.ssh/id_rsa /etc/chef-server/chef-validator.pem
    knife cookbook create temp
fi

mkdir /tmp/resources
exit 0
