#!/bin/bash
# Handles activation of arbitrary resources in instance - simply copies them over to a temp directory
# Resource name + type is a unique identifier of the resource, and is resonable for file names

cat - > /tmp/resources/$RESUORCE_NAME.$RESOURCE_TYPE