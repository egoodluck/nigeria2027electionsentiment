#!/usr/bin/env bash
set -euo pipefail

RG="NigeriaElectionSentimentRG"
VM_NAME="NigeriaElectionSentimentVM"
LOCATION="southafricanorth"
ADMIN_USER="azureuser"
SSH_KEY_PATH="${HOME}/.ssh/id_rsa"
IMAGE="UbuntuLTS"
SIZE="Standard_B2s"   # >= 4 GB RAM needed for the transformer enrichment step

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI is not installed. Install it first: https://learn.microsoft.com/cli/azure/install-azure-cli"
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "You are not logged in to Azure. Run 'az login' first."
  exit 1
fi

if [ ! -f "$SSH_KEY_PATH" ]; then
  echo "SSH key not found at $SSH_KEY_PATH. Generating one..."
  mkdir -p "$(dirname "$SSH_KEY_PATH")"
  ssh-keygen -t rsa -b 4096 -f "$SSH_KEY_PATH" -N ""
fi

echo "Creating resource group $RG in $LOCATION..."
az group create --name "$RG" --location "$LOCATION"

echo "Creating VM $VM_NAME..."
az vm create \
  --resource-group "$RG" \
  --name "$VM_NAME" \
  --image "$IMAGE" \
  --size "$SIZE" \
  --admin-username "$ADMIN_USER" \
  --ssh-key-values "${SSH_KEY_PATH}.pub" \
  --public-ip-sku Standard

echo "Opening SSH port 22..."
az vm open-port --resource-group "$RG" --name "$VM_NAME" --port 22

PUBLIC_IP=$(az vm show --resource-group "$RG" --name "$VM_NAME" --show-details --query publicIps -o tsv)

echo "Azure VM created successfully. Connect with:"
echo "  ssh ${ADMIN_USER}@${PUBLIC_IP}"
echo

echo "Next steps: clone the repo on the VM or copy your local repo there, then run ./azure-setup.sh from the repo root."