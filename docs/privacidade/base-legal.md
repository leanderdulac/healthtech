# Hipótese do art. 11 usada pelo produto

Este arquivo registra a base que o software exige hoje. Não é parecer jurídico e não escolhe a razão social do controlador.

## Dado sensível

Frequência cardíaca, SpO2, pressão, temperatura e o identificador ligado a essa telemetria são dado pessoal sensível (art. 5, II).

A hipótese do art. 11 em uso é o inciso I: consentimento específico e destacado do titular. O companion só envia telemetria depois que a pessoa aceita o texto de `ConsentNotice`, gravado no cofre do aparelho com a versão `2026-09-28`. Sem esse aceite, medição ao vivo, envio manual, simulador e outbox não saem do aparelho.

A informação dada no aceite cobre a finalidade, o compartilhamento com a API e a nuvem que a hospeda, o caráter de apoio à decisão sem conduta obrigatória, e a forma de revogar.

## Dado pessoal que acompanha o envio

O identificador do paciente e o do dispositivo seguem o art. 7, I, o mesmo consentimento, porque não há outra hipótese escrita neste repositório.

## O que continua sem registro

A direção ainda não registrou aqui a razão social do controlador nem o encarregado. Revogar no app interrompe a coleta nova. A eliminação do que já está na API é o DELETE administrativo, não um botão do titular.
