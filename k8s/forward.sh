#!/usr/bin/env bash
# Exposes everything on localhost (same ports as docker compose). Ctrl+C to stop.
N="-n sentinelops"
kubectl $N port-forward svc/gateway 8000:8000 &
kubectl $N port-forward svc/grafana 3000:3000 &
kubectl $N port-forward svc/prometheus 9090:9090 &
kubectl $N port-forward svc/alertmanager 9093:9093 &
kubectl $N port-forward svc/ai-incident-assistant 8080:8000 &
wait
