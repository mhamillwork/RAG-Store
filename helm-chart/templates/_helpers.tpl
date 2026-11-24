{{- define "rag-store.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "rag-store.fullname" -}}
{{- if .Values.fullnameOverride }}{{ .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}{{ else }}{{ .Release.Name | trunc 63 | trimSuffix "-" }}{{ end }}
{{- end }}

{{- define "rag-store.labels" -}}
app.kubernetes.io/name: {{ include "rag-store.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: rag-store
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end }}

{{- define "rag-store.image" -}}
{{- $registry := .root.Values.global.imageRegistry -}}
{{- if $registry -}}{{ $registry }}/{{ .image }}:{{ .root.Values.global.imageTag }}{{- else -}}{{ .image }}:{{ .root.Values.global.imageTag }}{{- end -}}
{{- end }}

{{- define "rag-store.replicas" -}}
{{- if and .root.Values.maintenance.enabled .component.pauseInMaintenance -}}0{{- else -}}{{ .component.replicaCount }}{{- end -}}
{{- end }}
