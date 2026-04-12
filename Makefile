SERVICE = com.newsdigest.bot
PLIST   = ~/Library/LaunchAgents/$(SERVICE).plist
LOG_OUT = /Users/x/.newsdigest/logs/stdout.log
LOG_ERR = /Users/x/.newsdigest/logs/stderr.log

.PHONY: start stop restart status log err clean-log test

## 启动服务
start:
	launchctl load $(PLIST)

## 停止服务
stop:
	launchctl unload $(PLIST)

## 重启服务
restart:
	-launchctl unload $(PLIST)
	launchctl load $(PLIST)

## 查看服务状态
status:
	@launchctl list | grep newsdigest || echo "服务未运行"

## 查看实时日志
log:
	tail -f $(LOG_OUT)

## 查看错误日志
err:
	tail -f $(LOG_ERR)

## 清空日志
clean-log:
	> $(LOG_OUT)
	> $(LOG_ERR)

## 运行测试
test:
	python3 -m pytest newsdigest/tests/ -v
