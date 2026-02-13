## Connecting to Redis Valkey
Move đến thư mục chứa file .\connect-valkey.ps1 và chạy lệnh sau:
```
.\connect-valkey.ps1
```
OR

## Start port forwarding to Redis using SSM Session Manager

```
 aws ssm start-session --target i-01fc5b845face1d43 --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters '{\"host\":[\"heatmap-japan-valkey-001.0xqdzj.0001.apne1.cache.amazonaws.com\"],\"portNumber\":[\"6379\"],\"localPortNumber\":[\"6379\"]}'
```

