# Leash

**An ops agent that can fix your AWS at 3 AM, but can never destroy anything — because Cedar says so.**

Built by **thegoodengineers** (Bhumika Gurav, Chirag Honnyal, Abhijeet Sharma, Ayush V Upadhye)
during **First Commit — Bharat Builds Tour Stop 01** (WeMakeDevs x AWS), 17–20 September 2026.
Track: **Ship It**.

## The problem

Small teams run on AWS with nobody watching at 3 AM. A disk fills, a container crashes, an alarm
fires, and the fix is a boring known step — but the human is asleep. Letting an AI agent run the
fix is scary for a good reason: an agent with admin keys can also delete the database, and a clever
prompt can talk it into doing so. So nobody automates the fix.

## What Leash does

A Strands agent receives CloudWatch alarms, diagnoses, and runs the fix — where **every action is
first checked against Cedar policies in Amazon Verified Permissions**. It can restart, scale and
clean up; it can never delete, never touch anything tagged `env=prod`, and never scale past a cap,
no matter how it is prompted. Every decision, allowed or denied, is written to an audit trail.

_Architecture, deploy steps, demo script and writeup follow as the build progresses._
