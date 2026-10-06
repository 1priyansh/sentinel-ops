#!/usr/bin/env bash
# Run from the sentinelops folder. Needs: minikube running (minikube start), docker, kubectl.
set -e
eval $(minikube docker-env)          # build images straight into minikube
for s in gateway user-service product-service order-service payment-service ai-incident-assistant; do
  docker build -q -t sentinelops/$s:latest --build-arg SERVICE=$s ./services
done
kubectl create ns sentinelops --dry-run=client -o yaml | kubectl apply -f -
cm() { kubectl -n sentinelops create configmap "$@" --dry-run=client -o yaml | kubectl apply -f -; }
cm prometheus-config --from-file=monitoring/prometheus.yml --from-file=monitoring/alerts.yml
cm alertmanager-config --from-file=monitoring/alertmanager.yml
cm grafana-ds --from-file=monitoring/grafana/datasources.yml
cm promtail-config --from-file=monitoring/promtail-k8s.yml
cm loadgen --from-file=loadgen.py
[ -n "$ANTHROPIC_API_KEY" ] && kubectl -n sentinelops create secret generic ai-keys --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/sentinelops.yaml
echo "Deployed. Check: kubectl -n sentinelops get pods   then run: bash k8s/forward.sh"
