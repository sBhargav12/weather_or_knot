#!/usr/bin/env bash
set -u

COMPARTMENT_ID="ocid1.tenancy.oc1..aaaaaaaadjqpvibvsxpmbxpv2k6edjl6tsbar6sr6j7ztpvd7hdd3orw3sda"
IMAGE_ID="ocid1.image.oc1.iad.aaaaaaaac6ozbxqea5kb7to5qu3asvnqj5f4j6gcxhxipeafefzpwtxm6mwa"
SSH_KEY_FILE="/Users/bhargavsukhavasi/.ssh/oracle_kalshi.pub"
DISPLAY_PREFIX="kalshi-paper-bot-a1"
OCPUS="${A1_OCPUS:-2}"
MEMORY_GB="${A1_MEMORY_GB:-12}"
SLEEP_SECONDS="${A1_RETRY_SECONDS:-120}"

AD_NAMES=(
  "OpeI:US-ASHBURN-AD-1"
  "OpeI:US-ASHBURN-AD-2"
  "OpeI:US-ASHBURN-AD-3"
)

SUBNET_IDS=(
  "ocid1.subnet.oc1.iad.aaaaaaaaztvin4ob2nou63zdtt5724jaw3f4evannvi2aaufyxnksmtvvbaa"
  "ocid1.subnet.oc1.iad.aaaaaaaa43rr6pi3wwl3dmnmh6wk34x4irdpt5wnsa5ekk2bbr54f2qz4kpa"
  "ocid1.subnet.oc1.iad.aaaaaaaafckv5ckrjk4lf3v6ne7icrhnzurkhbmw4itc5bxiloniukanjrba"
)

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

a1_exists() {
  oci compute instance list \
    --compartment-id "$COMPARTMENT_ID" \
    --all \
    --query "data[?shape=='VM.Standard.A1.Flex' && \"lifecycle-state\"!='TERMINATED'].id | length(@)" \
    --raw-output 2>/dev/null | grep -qv '^0$'
}

log "Starting A1 capacity loop: ${OCPUS} OCPU, ${MEMORY_GB} GB RAM, retry=${SLEEP_SECONDS}s"

while true; do
  if a1_exists; then
    log "A1 instance already exists; stopping capacity loop."
    oci compute instance list \
      --compartment-id "$COMPARTMENT_ID" \
      --all \
      --query "data[?shape=='VM.Standard.A1.Flex'].{name:\"display-name\",state:\"lifecycle-state\",ad:\"availability-domain\",id:id}" \
      --output table
    exit 0
  fi

  for idx in "${!AD_NAMES[@]}"; do
    ad="${AD_NAMES[$idx]}"
    subnet="${SUBNET_IDS[$idx]}"
    display_name="${DISPLAY_PREFIX}-ad$((idx + 1))"
    log "Trying ${display_name} in ${ad}"

    if oci compute instance launch \
      --availability-domain "$ad" \
      --compartment-id "$COMPARTMENT_ID" \
      --subnet-id "$subnet" \
      --display-name "$display_name" \
      --shape VM.Standard.A1.Flex \
      --shape-config "{\"ocpus\":${OCPUS},\"memoryInGBs\":${MEMORY_GB}}" \
      --image-id "$IMAGE_ID" \
      --assign-public-ip true \
      --ssh-authorized-keys-file "$SSH_KEY_FILE"; then
      log "Launch command accepted for ${display_name}; waiting for OCI to expose the instance."
      sleep 30
      if a1_exists; then
        log "A1 instance created; stopping capacity loop."
        oci compute instance list \
          --compartment-id "$COMPARTMENT_ID" \
          --all \
          --query "data[?shape=='VM.Standard.A1.Flex'].{name:\"display-name\",state:\"lifecycle-state\",ad:\"availability-domain\",id:id}" \
          --output table
        exit 0
      fi
    else
      log "No capacity or launch failed for ${display_name}; continuing."
    fi
  done

  log "Cycle complete; sleeping ${SLEEP_SECONDS}s"
  sleep "$SLEEP_SECONDS"
done
