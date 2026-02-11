# OpenSummit

OpenSummit is a lightweight Discord bot that evaluates weekend weather conditions and notifies you when outdoor activities like hiking or camping are realistically worth it.

It does not forward raw forecasts.
It makes a decision.

---

## Overview

OpenSummit monitors upcoming weekend forecasts and applies a deterministic evaluation model based on configurable thresholds.

Instead of spamming weather updates, the bot calculates a structured outcome:

**GO** – Conditions suitable for hiking or camping
**NO-GO** – Conditions not recommended

Notifications are only sent when the decision changes.

---

## Core Features

- Automatic weekend detection  
- Temperature, wind, precipitation, and cloud evaluation  
- Score-based or rule-based decision engine  
- State persistence to prevent repeated alerts  
- Minimal Discord output  
- Designed for self-hosting environments  

---

## Architecture

OpenSummit is structured into independent components:

1. **Forecast Fetcher**  
   Retrieves weather data from an external API.

2. **Decision Engine**  
   Applies configurable thresholds or scoring rules.

3. **State Manager**  
   Stores the last weekend decision to avoid duplicate notifications.

4. **Discord Interface**  
   Sends formatted messages to a defined channel.

This separation ensures clarity and maintainability.

---

## Configuration

You define what “good weather” means.

Configurable parameters may include:

- Minimum daytime temperature
- Maximum daytime temperature  
- Maximum wind speed  
- Maximum precipitation probability  
- Maximum cloud coverage  
- Minimum required decision score  

All thresholds are adjustable.

---

## Intended Use

OpenSummit is designed for:

- Hiking groups  
- Camping enthusiasts  
- Outdoor communities  
- Personal automation setups  

It is not a safety-critical system and does not replace official weather advisories.

---

## Roadmap

- Region selection per user  
- Role-based notifications  
- Slash command configuration  
- Multi-location support  
- Optional web dashboard

