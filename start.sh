#!/bin/bash

# Default to standard docker-compose.yml
COMPOSE_FILES="-f docker-compose.yml"
USE_GPU=false

# Simple argument parsing
for arg in "$@"
do
    case $arg in
        --gpu)
        USE_GPU=true
        shift
        ;;
        --help)
        echo "Usage: ./start.sh [--gpu]"
        echo "  --gpu   Enable NVIDIA GPU support"
        exit 0
        ;;
    esac
done

if [ "$USE_GPU" = true ]; then
    echo "Sending love to the  GPU..."
    COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.gpu.yml"
else
    echo "GPU is overrated, signed -the CPU gang..."
fi

# Execute docker compose up
echo "Command: docker compose $COMPOSE_FILES up -d"
docker compose $COMPOSE_FILES up -d

# Show status
echo "Waiting for services..."
sleep 2
docker compose ps
