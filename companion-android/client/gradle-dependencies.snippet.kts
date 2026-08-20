// O app já depende do módulo :client — não copie estes artefatos para :app.
//
// settings.gradle.kts:
//   include(":client")
//   include(":app")
//
// app/build.gradle.kts:
//   implementation(project(":client"))
//
// local.properties (gitignored):
//   HEALTHTECH_BASE_URL=http://10.0.2.2:8080
//   HEALTHTECH_INGEST_API_KEY=
