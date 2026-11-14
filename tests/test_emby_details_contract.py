"""Regression for Emby 4.10's global Items?Ids lookup and write guard."""
import copy
import pytest
from nfocheck.emby import EmbyGateway
from test_emby import setup, Stop

class QueryGateway(EmbyGateway):
    def __init__(self, cfg, before, fresh):
        super().__init__(cfg, {})
        self.before, self.fresh, self.calls = before, fresh, []
    def request(self, server, method, path, params=None):
        self.calls.append((method, path, params or {}))
        if method == 'POST': return None
        assert path == 'Items'
        if 'Ids' in params: return {'Items': copy.deepcopy(self.fresh)}
        return {'Items': [copy.deepcopy(self.before)], 'TotalRecordCount': 1}

@pytest.mark.parametrize('fresh', [[], [{'Id':'other'}], [{'Id':'1'}, {'Id':'1'}]])
def test_missing_or_ambiguous_fresh_id_never_posts(tmp_path, fresh):
    cfg, inspector, record, before = setup(tmp_path, 'changed')
    record['results'] = {'nfo': {'status':'repaired'}}
    gateway = QueryGateway(cfg, before, fresh)
    assert gateway.refresh(record, inspector, Stop())[0]['status'] == 'failed'
    assert not any(m == 'POST' for m, _, _ in gateway.calls)

@pytest.mark.parametrize('change', [{'Path':'/other/Film.mkv'}, {'Type':'Series'}, {'ProviderIds':{'Tmdb':'999'}}])
def test_fresh_identity_conflict_never_posts(tmp_path, change):
    cfg, inspector, record, before = setup(tmp_path, 'changed')
    record['local']['ids'] = {'tmdb':'1'}
    before['ProviderIds'] = {'Tmdb':'1'}
    record['results'] = {'nfo': {'status':'repaired'}}
    gateway = QueryGateway(cfg, before, [{**before, **change}])
    assert gateway.refresh(record, inspector, Stop())[0]['status'] == 'failed'
    assert not any(m == 'POST' for m, _, _ in gateway.calls)

def test_exact_lookup_used_before_post_and_during_verification(tmp_path):
    cfg, inspector, record, before = setup(tmp_path, 'changed')
    record['results'] = {'nfo': {'status':'repaired'}}
    gateway = QueryGateway(cfg, before, [{**before, 'Overview':'Complete'}])
    result = gateway.refresh(record, inspector, Stop())
    assert result[0]['status'] == 'verified'
    details = [(m,p,q) for m,p,q in gateway.calls if 'Ids' in q]
    assert len(details) >= 2
    assert all(p == 'Items' and q['Ids']=='1' and q['Limit']==2 and 'LockedFields' in q['Fields'] for m,p,q in details)
    assert sum(m=='POST' for m,p,q in gateway.calls)==1
