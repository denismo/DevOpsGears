#!/bin/bash
# Install the associated Chef script into the running instance. Assumes that chef is already running

cat - > /tmp/chef/cookbooks/temp/recipes/default.rb

chef-client -z -o temp
