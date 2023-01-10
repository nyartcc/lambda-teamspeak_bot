# ZNY Lambda Teamspeak Bot

Author: @trevorc21

## Description
This Lambda function runs on an EventBridge CRON schedule to automatically add Teamspeak 3 groups to users connected to the server. Users are matched to their website profile by the bot messaging any un-matched users asking them to connect their TS3 account to their website account. Once this is done, the bot will add both permanent server groups such as "New York Controller", "Training Staff" or titles as appropriate. Any unmatched users will get the "New York Guest" tag.

Controllers that are connected to VATSIM, controlling a ZNY position will
automatically get a prefix tag (such as [2G] representing JFK_APP, CAM sector)
as long as they are connected, to easily idenitfy who is controlling what
position.

## Requirements
AWS Lambda
Python 3.9
Teamspeak SDK
SQLAlchemy

## Lambda Configurations
The Teamspeak SDK and SQLAlchemy are not part of the standard libraries available
to Lambda functions and you will need to make them available to Lambda. This is
done using [Layers](https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html) in Lambda.

The easiest way to create a new layer is following these instructions for
making the Teamspeak SDK available:

```bash
# Create a new empty folder for the layer
mkdir teamspeak_layer && cd teamspeak_layer

# Create a Python folder. Required (?)
mkdir python && cd python

# Install the required libraries
pip install ts3 -t ./

# Zip the library into a package for Lambda
cd .. && zip -r python.zip python/
```

This `.zip` folder can then be uploaded to AWS Lambda as a layer and you can
give the layer a useful name. Note: You can, if you wish, install multiple (or
all) libraries in a single layer, but it becomes more of a monolith anytime you
need to update a library.


