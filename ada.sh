#!/bin/bash

# Cliente stand-alone para usar Ada remotamente desde cualquier proyecto
# https://github.com/sebolio/ada


API="http://localhost:3839"

if [ $# -lt 2 ]; then
    echo "Uso: $0 [topic] \"mensaje\" [message_id]"
    exit 1
fi

topic="$1"
message="$2"
updateId="${3:-}"

response=$(curl -s -X POST "$API/say" \
    -d "text=$message" \
    -d "topic=$topic" \
    ${updateId:+-d "updateId=$updateId"})

if echo "$response" | grep -q '"success":false'; then
    echo "invalid_topic"
    exit 1
else
    message_id=$(echo "$response" | sed -n 's/.*"message_id":\([^"]*\),".*/\1/p')
    if [ -n "$message_id" ]; then
        echo "$message_id"
        exit 0
    else
        echo "no_message_id"
        echo $response
        exit 1
    fi
fi
