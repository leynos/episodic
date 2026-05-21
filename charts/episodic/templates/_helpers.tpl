{{/*
Expand the name of the chart.
*/}}
{{- define "episodic.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "episodic.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Create chart labels.
*/}}
{{- define "episodic.labels" -}}
helm.sh/chart: {{ include "episodic.chart" . }}
{{ include "episodic.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "episodic.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Selector labels.
*/}}
{{- define "episodic.selectorLabels" -}}
app.kubernetes.io/name: {{ include "episodic.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Create the service account name.
*/}}
{{- define "episodic.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "episodic.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Secret name cascade:
- existingSecretName reuses an operator-managed Secret that already exists.
- externalSecret.targetName names the ESO-managed Secret when ExternalSecret is enabled.
- release fullname is the chart-owned fallback name for inline/default Secret references.
*/}}
{{- define "episodic.secretName" -}}
{{- if .Values.existingSecretName -}}
{{- .Values.existingSecretName -}}
{{- else if and .Values.externalSecret.enabled .Values.externalSecret.targetName -}}
{{- .Values.externalSecret.targetName -}}
{{- else -}}
{{- include "episodic.fullname" . -}}
{{- end -}}
{{- end -}}
