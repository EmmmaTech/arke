# Arke

A Python Discord API Wrapper made from the ground up... I guess.

## Why

I got really bored while on vacation one day. So I started this project. 
I don't have any intentions of taking this project seriously (because I tried that before and it didn't work), 
but we will see what happens.

## Name

It comes from the Greek Mythological figure named Arke, who was a messenger goddess for the Titans. 
The name means "swift", which implies this Discord API Wrapper is fast. It probably is.

## What's Implemented

- REST API
    - [x] Ratelimiting
    - [x] Error Parsing
    - [x] Bot & Bearer Authentication
    - [ ] Route Wrapping
        - NOTE: this library will not wrap the routes themselves because they constantly change.
          This library will only give the foundations needed for route wrapping for others to do it.
- Gateway
    - [ ] Connection Handling
    - [ ] Events/Dispatcher
    - [ ] Ratelimiting
    - [ ] Error Handling
    - [ ] Sharding
