#!/bin/bash

keyName=`$DEVOPSGEARS get-resource-attribute $RESOURCE_ANCESTOR_NAME desc/key-name`
login=`$DEVOPSGEARS get-resource-attribute $RESOURCE_ANCESTOR_NAME desc/login`
ip=`$DEVOPSGEARS get-resource-attribute $RESOURCE_ANCESTOR_NAME dynamicState/privateIP`

cat - | ssh -i $KEYS/$keyName $login@$ip "cat > /tmp/$HANDLER_NAME.$HANDLER_TYPE; chmod +x $HANDLER_NAME.$HANDLER_TYPE"
ssh -i $KEYS/$keyName $login@$ip "/tmp/$HANDLER_NAME.$HANDLER_TYPE" | `$DEVOPSGEARS get-resource-data $RESORCE_NAME`

