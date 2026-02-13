# connect-valkey.ps1
# ========================================
# VALKEY CONNECTION SCRIPT
# ========================================

# THAY ĐỔI SAU KHI CHẠY TERRAFORM
$BASTION_ID = "i-01fc5b845face1d43"  # Get from: terraform output bastion_instance_id

$VALKEY_ENDPOINT = "heatmap-japan-valkey-001.0xqdzj.0001.apne1.cache.amazonaws.com"
$LOCAL_PORT = 6379
$REMOTE_PORT = 6379

# ========================================
# FUNCTIONS
# ========================================

function Check-Dependencies {
    Write-Host " Checking dependencies..." -ForegroundColor Blue
    
    if (!(Get-Command aws -ErrorAction SilentlyContinue)) {
        Write-Host " AWS CLI not found!" -ForegroundColor Red
        exit 1
    }
    
    if (!(Get-Command session-manager-plugin -ErrorAction SilentlyContinue)) {
        Write-Host " Session Manager Plugin not found!" -ForegroundColor Red
        exit 1
    }
    
    Write-Host " All dependencies installed" -ForegroundColor Green
}

function Check-Bastion {
    Write-Host "` Checking bastion instance..." -ForegroundColor Blue
    
    $status = aws ec2 describe-instances `
        --instance-ids $BASTION_ID `
        --query 'Reservations[0].Instances[0].State.Name' `
        --output text 2>$null
    
    if (!$status) {
        Write-Host " Bastion instance not found: $BASTION_ID" -ForegroundColor Red
        exit 1
    }
    
    if ($status -ne "running") {
        Write-Host "  Bastion is $status. Starting..." -ForegroundColor Yellow
        aws ec2 start-instances --instance-ids $BASTION_ID | Out-Null
        Write-Host " Waiting for instance to start..." -ForegroundColor Yellow
        aws ec2 wait instance-running --instance-ids $BASTION_ID
    }
    
    Write-Host " Bastion is running" -ForegroundColor Green
}

function Check-SSM {
    Write-Host "Checking SSM connectivity..." -ForegroundColor Blue
    
    $ssmStatus = aws ssm describe-instance-information `
        --filters "Key=InstanceIds,Values=$BASTION_ID" `
        --query 'InstanceInformationList[0].PingStatus' `
        --output text 2>$null
    
    if ($ssmStatus -ne "Online") {
        Write-Host "  SSM agent status: $ssmStatus" -ForegroundColor Yellow
        Write-Host " Waiting for SSM agent (up to 60s)..." -ForegroundColor Yellow
        
        for ($i = 1; $i -le 12; $i++) {
            Start-Sleep -Seconds 5
            $ssmStatus = aws ssm describe-instance-information `
                --filters "Key=InstanceIds,Values=$BASTION_ID" `
                --query 'InstanceInformationList[0].PingStatus' `
                --output text 2>$null
            
            if ($ssmStatus -eq "Online") {
                break
            }
            Write-Host "." -NoNewline
        }
        Write-Host ""
        
        if ($ssmStatus -ne "Online") {
            Write-Host " SSM agent not responding" -ForegroundColor Red
            Write-Host "  Bastion subnet may not have internet access" -ForegroundColor Yellow
            exit 1
        }
    }
    
    Write-Host " SSM agent is online" -ForegroundColor Green
}

function Start-PortForward {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " Starting Port Forward" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host " Bastion:   $BASTION_ID" -ForegroundColor Blue
    Write-Host " Endpoint:  $VALKEY_ENDPOINT" -ForegroundColor Blue
    Write-Host " Mapping:   localhost:$LOCAL_PORT → Valkey:$REMOTE_PORT" -ForegroundColor Blue
    Write-Host ""
    Write-Host "  KEEP THIS WINDOW OPEN!" -ForegroundColor Yellow
    Write-Host "  Press Ctrl+C to disconnect" -ForegroundColor Yellow
    Write-Host ""
    Write-Host " Ready! Connect RedisInsight to:" -ForegroundColor Green
    Write-Host "   Host: localhost" -ForegroundColor Green
    Write-Host "   Port: $LOCAL_PORT" -ForegroundColor Green
    Write-Host "   Database: 1" -ForegroundColor Green
    Write-Host ""
    
    # Build SSM parameters JSON - AWS CLI requires string values in arrays
    aws --% ssm start-session --target i-01fc5b845face1d43 --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters "{\"host\":[\"heatmap-japan-valkey-001.0xqdzj.0001.apne1.cache.amazonaws.com\"],\"portNumber\":[\"6379\"],\"localPortNumber\":[\"6379\"]}"
}

# ========================================
# MAIN
# ========================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Valkey Connection Manager" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

Check-Dependencies
Check-Bastion
Check-SSM
Start-PortForward
