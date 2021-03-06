# -*- coding: utf-8 -*-

from __future__ import absolute_import

from datetime import timedelta

import six
import datetime
from django.utils import timezone
from exam import fixture

from sentry.api.serializers import serialize
from sentry.api.serializers.models.project import (
    bulk_fetch_project_latest_releases,
    ProjectWithOrganizationSerializer,
    ProjectWithTeamSerializer,
    ProjectSummarySerializer,
)
from sentry.models import Deploy, Environment, EnvironmentProject, Release, ReleaseProjectEnvironment
from sentry.testutils import TestCase


class ProjectSerializerTest(TestCase):
    def test_simple(self):
        user = self.create_user(username='foo')
        organization = self.create_organization(owner=user)
        team = self.create_team(organization=organization)
        project = self.create_project(teams=[team], organization=organization, name='foo')

        result = serialize(project, user)

        assert result['slug'] == project.slug
        assert result['name'] == project.name
        assert result['id'] == six.text_type(project.id)

    def test_member_access(self):
        user = self.create_user(username='foo')
        organization = self.create_organization()
        self.create_member(user=user, organization=organization)
        team = self.create_team(organization=organization)
        project = self.create_project(teams=[team])

        result = serialize(project, user)

        assert result['hasAccess'] is True
        assert result['isMember'] is False

        organization.flags.allow_joinleave = False
        organization.save()
        result = serialize(project, user)
        # after changing to allow_joinleave=False
        assert result['hasAccess'] is False
        assert result['isMember'] is False

        self.create_team_membership(user=user, team=team)
        result = serialize(project, user)
        # after giving them access to team
        assert result['hasAccess'] is True
        assert result['isMember'] is True

    def test_admin_access(self):
        user = self.create_user(username='foo')
        organization = self.create_organization()
        self.create_member(user=user, organization=organization, role='admin')
        team = self.create_team(organization=organization)
        project = self.create_project(teams=[team])

        result = serialize(project, user)
        result.pop('dateCreated')

        assert result['hasAccess'] is True
        assert result['isMember'] is False

        organization.flags.allow_joinleave = False
        organization.save()
        result = serialize(project, user)
        # after changing to allow_joinleave=False
        assert result['hasAccess'] is False
        assert result['isMember'] is False

        self.create_team_membership(user=user, team=team)
        result = serialize(project, user)
        # after giving them access to team
        assert result['hasAccess'] is True
        assert result['isMember'] is True

    def test_manager_access(self):
        user = self.create_user(username='foo')
        organization = self.create_organization()
        self.create_member(user=user, organization=organization, role='manager')
        team = self.create_team(organization=organization)
        project = self.create_project(teams=[team])

        result = serialize(project, user)

        assert result['hasAccess'] is True
        assert result['isMember'] is False

        organization.flags.allow_joinleave = False
        organization.save()
        result = serialize(project, user)
        # after changing to allow_joinleave=False
        assert result['hasAccess'] is True
        assert result['isMember'] is False

        self.create_team_membership(user=user, team=team)
        result = serialize(project, user)
        # after giving them access to team
        assert result['hasAccess'] is True
        assert result['isMember'] is True

    def test_owner_access(self):
        user = self.create_user(username='foo')
        organization = self.create_organization()
        self.create_member(user=user, organization=organization, role='owner')
        team = self.create_team(organization=organization)
        project = self.create_project(teams=[team])

        result = serialize(project, user)

        assert result['hasAccess'] is True
        assert result['isMember'] is False

        organization.flags.allow_joinleave = False
        organization.save()
        result = serialize(project, user)
        # after changing to allow_joinleave=False
        assert result['hasAccess'] is True
        assert result['isMember'] is False

        self.create_team_membership(user=user, team=team)
        result = serialize(project, user)
        # after giving them access to team
        assert result['hasAccess'] is True
        assert result['isMember'] is True


class ProjectWithTeamSerializerTest(TestCase):
    def test_simple(self):
        user = self.create_user(username='foo')
        organization = self.create_organization(owner=user)
        team = self.create_team(organization=organization)
        project = self.create_project(teams=[team], organization=organization, name='foo')

        result = serialize(project, user, ProjectWithTeamSerializer())

        assert result['slug'] == project.slug
        assert result['name'] == project.name
        assert result['id'] == six.text_type(project.id)
        assert result['team'] == {
            'id': six.text_type(
                team.id),
            'slug': team.slug,
            'name': team.name}


class ProjectSummarySerializerTest(TestCase):
    def setUp(self):
        self.date = datetime.datetime(2018, 1, 12, 3, 8, 25, tzinfo=timezone.utc)
        self.user = self.create_user(username='foo')
        self.organization = self.create_organization(owner=self.user)
        team = self.create_team(organization=self.organization)
        self.project = self.create_project(teams=[team], organization=self.organization, name='foo')
        self.project.flags.has_releases = True
        self.project.save()

        self.release = self.create_release(self.project)

        environment_1 = Environment.objects.create(
            organization_id=self.organization.id,
            name='production',
        )
        environment_1.add_project(self.project)
        environment_1.save()
        environment_2 = Environment.objects.create(
            organization_id=self.organization.id,
            name='staging',
        )
        environment_2.add_project(self.project)
        environment_2.save()
        deploy = Deploy.objects.create(
            environment_id=environment_1.id,
            organization_id=self.organization.id,
            release=self.release,
            date_finished=self.date
        )
        ReleaseProjectEnvironment.objects.create(
            project_id=self.project.id,
            release_id=self.release.id,
            environment_id=environment_1.id,
            last_deploy_id=deploy.id
        )

    def test_simple(self):
        result = serialize(self.project, self.user, ProjectSummarySerializer())

        assert result['id'] == six.text_type(self.project.id)
        assert result['name'] == self.project.name
        assert result['slug'] == self.project.slug
        assert result['firstEvent'] == self.project.first_event
        assert 'releases' in result['features']
        assert result['platform'] == self.project.platform

        assert result['latestDeploys'] == {
            'production': {'dateFinished': self.date, 'version': self.release.version}
        }
        assert result['latestRelease'] == {'version': self.release.version}
        assert result['environments'] == ['production', 'staging']

    def test_no_enviroments(self):
        # remove environments and related models
        Deploy.objects.all().delete()
        Release.objects.all().delete()
        Environment.objects.all().delete()

        result = serialize(self.project, self.user, ProjectSummarySerializer())

        assert result['id'] == six.text_type(self.project.id)
        assert result['name'] == self.project.name
        assert result['slug'] == self.project.slug
        assert result['firstEvent'] == self.project.first_event
        assert 'releases' in result['features']
        assert result['platform'] == self.project.platform

        assert result['latestDeploys'] is None
        assert result['latestRelease'] is None
        assert result['environments'] == []

    def test_avoid_hidden_and_no_env(self):
        hidden_env = Environment.objects.create(
            organization_id=self.organization.id,
            name='staging 2',
        )
        EnvironmentProject.objects.create(
            project=self.project,
            environment=hidden_env,
            is_hidden=True,
        )

        no_env = Environment.objects.create(
            organization_id=self.organization.id,
            name='',
        )
        no_env.add_project(self.project)
        no_env.save()

        result = serialize(self.project, self.user, ProjectSummarySerializer())

        assert result['id'] == six.text_type(self.project.id)
        assert result['name'] == self.project.name
        assert result['slug'] == self.project.slug
        assert result['firstEvent'] == self.project.first_event
        assert 'releases' in result['features']
        assert result['platform'] == self.project.platform

        assert result['latestDeploys'] == {
            'production': {'dateFinished': self.date, 'version': self.release.version}
        }
        assert result['latestRelease'] == {'version': self.release.version}
        assert result['environments'] == ['production', 'staging']


class ProjectWithOrganizationSerializerTest(TestCase):
    def test_simple(self):
        user = self.create_user(username='foo')
        organization = self.create_organization(owner=user)
        team = self.create_team(organization=organization)
        project = self.create_project(teams=[team], organization=organization, name='foo')

        result = serialize(project, user, ProjectWithOrganizationSerializer())

        assert result['slug'] == project.slug
        assert result['name'] == project.name
        assert result['id'] == six.text_type(project.id)
        assert result['organization'] == serialize(organization, user)


class BulkFetchProjectLatestReleases(TestCase):
    @fixture
    def project(self):
        return self.create_project(
            teams=[self.team],
            organization=self.organization,
        )

    @fixture
    def other_project(self):
        return self.create_project(
            teams=[self.team],
            organization=self.organization,
        )

    def test_single_no_release(self):
        assert bulk_fetch_project_latest_releases([self.project]) == []

    def test_single_release(self):
        release = self.create_release(
            self.project,
            date_added=timezone.now() - timedelta(minutes=5),
        )
        assert bulk_fetch_project_latest_releases([self.project]) == [release]
        newer_release = self.create_release(self.project)
        assert bulk_fetch_project_latest_releases([self.project]) == [newer_release]

    def test_multi_no_release(self):
        assert bulk_fetch_project_latest_releases(
            [self.project, self.other_project],
        ) == []

    def test_multi_mixed_releases(self):
        release = self.create_release(self.project)
        assert set(bulk_fetch_project_latest_releases(
            [self.project, self.other_project],
        )) == set([release])

    def test_multi_releases(self):
        release = self.create_release(
            self.project,
            date_added=timezone.now() - timedelta(minutes=5),
        )
        other_project_release = self.create_release(self.other_project)
        assert set(bulk_fetch_project_latest_releases(
            [self.project, self.other_project],
        )) == set([release, other_project_release])
        release_2 = self.create_release(self.project)
        assert set(bulk_fetch_project_latest_releases(
            [self.project, self.other_project],
        )) == set([release_2, other_project_release])
