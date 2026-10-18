def integration_decision(worker_result: dict, verification: dict) -> str:
    if worker_result.get('status') == 'implemented':
        return 'READY_TO_INTEGRATE'
    return 'REJECTED'
