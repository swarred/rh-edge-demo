#!/usr/bin/env bash
# Install ACM 2.17 and apply mission edge fleet stubs
# Run from rh-edge-demo-automation/ after oc login to the new cluster
set -euo pipefail

echo "=== Installing ACM 2.17 ==="

oc apply -f - <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: open-cluster-management
  labels:
    openshift.io/cluster-monitoring: "true"
EOF

oc apply -f - <<'EOF'
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: open-cluster-management
  namespace: open-cluster-management
spec:
  targetNamespaces:
    - open-cluster-management
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: advanced-cluster-management
  namespace: open-cluster-management
spec:
  channel: release-2.17
  installPlanApproval: Automatic
  name: advanced-cluster-management
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF

echo "Waiting for ACM operator CSV..."
until oc get csv -n open-cluster-management 2>/dev/null | grep -q "Succeeded"; do
  sleep 10; echo -n "."
done
echo " CSV ready"

oc apply -f - <<'EOF'
apiVersion: operator.open-cluster-management.io/v1
kind: MultiClusterHub
metadata:
  name: multiclusterhub
  namespace: open-cluster-management
spec: {}
EOF

echo "Waiting for MultiClusterHub to be Running (10-20 min on multi-master)..."
until [ "$(oc get multiclusterhub multiclusterhub -n open-cluster-management \
  -o jsonpath='{.status.phase}' 2>/dev/null)" = "Running" ]; do
  sleep 30; echo -n "."
done
echo " MCH Running!"

echo ""
echo "=== Applying mission edge fleet stubs ==="
oc apply -f ../rh-edge-demo/ocp/acm/managed-clusters.yaml

echo ""
echo "=== Done ==="
echo "ACM console: $(oc get route multicloud-console -n open-cluster-management \
  -o jsonpath='https://{.spec.host}' 2>/dev/null || echo 'check oc get routes -n open-cluster-management')"
echo ""
echo "Fleet clusters:"
oc get managedclusters
