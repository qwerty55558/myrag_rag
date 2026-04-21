#!/bin/bash
# 환경변수를 SQL에 주입
sed -i "s/__RAG_DB_PASSWORD__/${RAG_DB_PASSWORD:-changeme}/g" /docker-entrypoint-initdb.d/01-init.sql
sed -i "s/__DB_SPRING_PW__/${DB_SPRING_PW:-spring_pw}/g" /docker-entrypoint-initdb.d/01-init.sql
